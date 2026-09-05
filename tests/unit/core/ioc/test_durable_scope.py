"""Unit tests for durable provider scope resolution."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, cast

import pytest
from starlette.requests import Request

from bustan import Injectable, Module, Scope
from bustan.core.errors import InvalidProviderError, ProviderResolutionError
from bustan.core.ioc.container import build_container
from bustan.core.ioc.registry import Binding
from bustan.core.ioc.scopes import CACHE_MISS, ScopeManager
from bustan.core.module.graph import build_module_graph

if TYPE_CHECKING:
    from tests.conftest import HttpRequestFactory


def test_durable_scope_reuses_instances_for_the_same_context_key(
    build_http_request: HttpRequestFactory,
) -> None:
    @Injectable(scope=Scope.DURABLE)
    class DurableService:
        @classmethod
        def get_durable_context_key(cls, request: Request | None) -> str:
            assert request is not None
            return request.headers["x-tenant-id"]

    @Module(providers=[DurableService], exports=[DurableService])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    request = build_http_request(path="/items", headers=[(b"x-tenant-id", b"tenant-a")])

    first = cast(Any, container.resolve(DurableService, module=AppModule, request=request))
    second = cast(Any, container.resolve(DurableService, module=AppModule, request=request))

    assert first is second


def test_durable_scope_isolated_by_context_key(build_http_request: HttpRequestFactory) -> None:
    @Injectable(scope=Scope.DURABLE)
    class DurableService:
        @classmethod
        def get_durable_context_key(cls, request: Request | None) -> str:
            assert request is not None
            return request.headers["x-tenant-id"]

    @Module(providers=[DurableService], exports=[DurableService])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    first_request = build_http_request(path="/items", headers=[(b"x-tenant-id", b"tenant-a")])
    second_request = build_http_request(path="/items", headers=[(b"x-tenant-id", b"tenant-b")])

    first = cast(Any, container.resolve(DurableService, module=AppModule, request=first_request))
    second = cast(Any, container.resolve(DurableService, module=AppModule, request=second_request))

    assert first is not second


def test_durable_scope_shares_instances_across_distinct_requests_with_the_same_key(
    build_http_request: HttpRequestFactory,
) -> None:
    @Injectable(scope=Scope.DURABLE)
    class DurableService:
        @classmethod
        def get_durable_context_key(cls, request: Request | None) -> str:
            assert request is not None
            return request.headers["x-tenant-id"]

    @Module(providers=[DurableService], exports=[DurableService])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    first_request = build_http_request(path="/items", headers=[(b"x-tenant-id", b"tenant-a")])
    second_request = build_http_request(path="/items", headers=[(b"x-tenant-id", b"tenant-a")])

    first = cast(Any, container.resolve(DurableService, module=AppModule, request=first_request))
    second = cast(Any, container.resolve(DurableService, module=AppModule, request=second_request))

    assert first is second


def test_durable_scope_requires_an_explicit_context_key_classmethod() -> None:
    # A durable instance is cached per context key, so a class that declares no hook
    # to derive one can never resolve for any request at all. There is no input that
    # makes it work, so the graph is refused while it is built rather than on
    # whichever request first happens to reach the provider.
    @Injectable(scope=Scope.DURABLE)
    class KeylessDurableService:
        pass

    @Module(providers=[KeylessDurableService], exports=[KeylessDurableService])
    class AppModule:
        pass

    with pytest.raises(InvalidProviderError, match="get_durable_context_key"):
        build_module_graph(AppModule)


def test_a_durable_binding_that_escaped_the_declaration_check_still_refuses_to_resolve(
    build_http_request: HttpRequestFactory,
) -> None:
    # The declaration check above is the only way a durable binding is created, so
    # this guards the invariant it establishes rather than a reachable input: a
    # durable cache keyed on anything but a declared key would hand one request's
    # instance to a later, unrelated one.
    class KeylessDurableService:
        pass

    @Module()
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    container.registry.register_binding(
        (AppModule, KeylessDurableService),
        Binding(
            token=KeylessDurableService,
            declaring_module=AppModule,
            resolver_kind="class",
            target=KeylessDurableService,
            scope=Scope.DURABLE,
        ),
    )
    container.registry.module_visibility[AppModule][KeylessDurableService] = AppModule
    request = build_http_request(path="/items", headers=[(b"x-tenant-id", b"tenant-a")])

    with pytest.raises(ProviderResolutionError, match="get_durable_context_key"):
        container.resolve(KeylessDurableService, module=AppModule, request=request)


def test_a_caller_varying_the_context_key_cannot_grow_the_durable_store(
    build_http_request: HttpRequestFactory,
) -> None:
    # The context key comes from a header, so whoever sends the request chooses how
    # many partitions there are. The store is bounded for that reason: an
    # unauthenticated caller rotating one header would otherwise retain an instance
    # and a construction lock per distinct value until the process ran out of memory.
    @Injectable(scope=Scope.DURABLE)
    class DurableService:
        @classmethod
        def get_durable_context_key(cls, request: Request | None) -> str:
            assert request is not None
            return request.headers["x-tenant-id"]

    @Module(providers=[DurableService], exports=[DurableService])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    scope_manager = container.scope_manager
    limit = scope_manager.durable_instances.limit

    for index in range(limit * 3):
        request = build_http_request(
            path="/items", headers=[(b"x-tenant-id", f"tenant-{index}".encode())]
        )
        container.resolve(DurableService, module=AppModule, request=request)

    assert len(scope_manager.durable_instances) == limit
    # The lock table holds the constructions in flight, and none is.
    assert len(scope_manager.construction_locks) == 0


def test_a_tenant_evicted_from_the_durable_store_is_built_again_when_it_returns(
    build_http_request: HttpRequestFactory,
) -> None:
    @Injectable(scope=Scope.DURABLE)
    class DurableService:
        @classmethod
        def get_durable_context_key(cls, request: Request | None) -> str:
            assert request is not None
            return request.headers["x-tenant-id"]

    @Module(providers=[DurableService], exports=[DurableService])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))

    def resolve(tenant: bytes) -> object:
        request = build_http_request(path="/items", headers=[(b"x-tenant-id", tenant)])
        return container.resolve(DurableService, module=AppModule, request=request)

    first = resolve(b"tenant-a")
    for index in range(container.scope_manager.durable_instances.limit):
        resolve(f"tenant-{index}".encode())

    # An evicted partition is a cache miss, not a wrong answer: the tenant that comes
    # back is served a new instance rather than another tenant's.
    assert resolve(b"tenant-a") is not first


def test_a_context_key_that_is_not_hashable_is_refused_by_name(
    build_http_request: HttpRequestFactory,
) -> None:
    # The key is a cache key, so an unhashable one has no partition to name. Refusing
    # it where it is built means the first resolve names the provider and the hook,
    # rather than a dict insert failing somewhere below with neither.
    @Injectable(scope=Scope.DURABLE)
    class DurableService:
        @classmethod
        def get_durable_context_key(cls, request: Request | None) -> Any:
            assert request is not None
            return [request.headers["x-tenant-id"]]

    @Module(providers=[DurableService], exports=[DurableService])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    request = build_http_request(path="/items", headers=[(b"x-tenant-id", b"tenant-a")])

    with pytest.raises(ProviderResolutionError) as raised:
        container.resolve(DurableService, module=AppModule, request=request)

    message = str(raised.value)
    assert "DurableService" in message
    assert "get_durable_context_key" in message
    assert "['tenant-a']" in message
    assert isinstance(raised.value.__cause__, TypeError)


def test_a_context_key_holding_an_unhashable_member_is_refused_too(
    build_http_request: HttpRequestFactory,
) -> None:
    # A tuple is hashable by protocol and still raises when a member is not, so the
    # check has to hash the key rather than ask whether its type claims to be hashable.
    @Injectable(scope=Scope.DURABLE)
    class DurableService:
        @classmethod
        def get_durable_context_key(cls, request: Request | None) -> Any:
            assert request is not None
            return (request.headers["x-tenant-id"], ["europe"])

    @Module(providers=[DurableService], exports=[DurableService])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    request = build_http_request(path="/items", headers=[(b"x-tenant-id", b"tenant-a")])

    with pytest.raises(ProviderResolutionError, match="get_durable_context_key"):
        container.resolve(DurableService, module=AppModule, request=request)


def test_a_tuple_context_key_still_partitions_the_durable_cache(
    build_http_request: HttpRequestFactory,
) -> None:
    # The refusal above rejects keys that cannot be hashed, not keys of an unfamiliar
    # type: a composite key is the ordinary way to partition on more than one field.
    @Injectable(scope=Scope.DURABLE)
    class DurableService:
        @classmethod
        def get_durable_context_key(cls, request: Request | None) -> tuple[str, str]:
            assert request is not None
            return (request.headers["x-tenant-id"], request.headers["x-region"])

    @Module(providers=[DurableService], exports=[DurableService])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))

    def resolve(tenant: bytes, region: bytes) -> object:
        request = build_http_request(
            path="/items", headers=[(b"x-tenant-id", tenant), (b"x-region", region)]
        )
        return container.resolve(DurableService, module=AppModule, request=request)

    first = resolve(b"tenant-a", b"eu")

    assert resolve(b"tenant-a", b"eu") is first
    assert resolve(b"tenant-a", b"us") is not first


def test_a_frozen_dataclass_context_key_still_partitions_the_durable_cache(
    build_http_request: HttpRequestFactory,
) -> None:
    @dataclass(frozen=True, slots=True)
    class TenantKey:
        tenant: str
        region: str

    @Injectable(scope=Scope.DURABLE)
    class DurableService:
        @classmethod
        def get_durable_context_key(cls, request: Request | None) -> TenantKey:
            assert request is not None
            return TenantKey(request.headers["x-tenant-id"], request.headers["x-region"])

    @Module(providers=[DurableService], exports=[DurableService])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))

    def resolve(tenant: bytes, region: bytes) -> object:
        request = build_http_request(
            path="/items", headers=[(b"x-tenant-id", tenant), (b"x-region", region)]
        )
        return container.resolve(DurableService, module=AppModule, request=request)

    first = resolve(b"tenant-a", b"eu")

    assert resolve(b"tenant-a", b"eu") is first
    assert resolve(b"tenant-b", b"eu") is not first


class DeclaringModule:
    """A stand-in module key for the durable keys under test."""


class Tokens(StrEnum):
    """A token whose members are equal to the bare strings they carry."""

    DB = "db"


def test_two_equal_tokens_of_different_types_keep_separate_durable_partitions() -> None:
    # A durable key carries the token as well as the partition, so the same collapse
    # the singleton table had reaches the durable store: one tenant's two providers
    # would share a partition and the second built would take the first's.
    manager = ScopeManager()
    enum_key = (DeclaringModule, Tokens.DB, "tenant-a")
    str_key = (DeclaringModule, "db", "tenant-a")

    manager.set_durable(enum_key, "from enum")
    manager.set_durable(str_key, "from str")

    assert manager.get_durable(enum_key) == "from enum"
    assert manager.get_durable(str_key) == "from str"
    assert len(manager.durable_instances) == 2
    assert list(manager.durable_instances) == [enum_key, str_key]

    del manager.durable_instances[enum_key]

    assert manager.get_durable(enum_key) is CACHE_MISS
    assert manager.get_durable(str_key) == "from str"


def test_a_true_token_and_a_one_token_keep_separate_durable_partitions() -> None:
    manager = ScopeManager()
    true_key = (DeclaringModule, True, "tenant-a")
    one_key = (DeclaringModule, 1, "tenant-a")

    manager.set_durable(true_key, "from true")
    manager.set_durable(one_key, "from one")

    assert manager.get_durable(true_key) == "from true"
    assert manager.get_durable(one_key) == "from one"
    assert len(manager.durable_instances) == 2


def test_telling_two_equal_tokens_apart_does_not_widen_the_durable_store() -> None:
    # The store is bounded whatever its keys are made of: the limit counts partitions,
    # and two tokens that are now told apart are two partitions against that limit.
    manager = ScopeManager(durable_instance_limit=2)

    manager.set_durable((DeclaringModule, Tokens.DB, "tenant-a"), "a")
    manager.set_durable((DeclaringModule, "db", "tenant-a"), "b")
    manager.set_durable((DeclaringModule, "db", "tenant-b"), "c")

    assert len(manager.durable_instances) == 2
    assert manager.get_durable((DeclaringModule, Tokens.DB, "tenant-a")) is CACHE_MISS
