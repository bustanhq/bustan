"""Unit tests for durable provider scope resolution."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pytest
from starlette.requests import Request

from bustan import Injectable, Module, Scope
from bustan.core.errors import InvalidProviderError, ProviderResolutionError
from bustan.core.ioc.container import build_container
from bustan.core.ioc.registry import Binding
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
