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
    from tests.conftest import RequestFactory


def test_durable_scope_reuses_instances_for_the_same_context_key(
    build_request: RequestFactory,
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
    request = build_request(path="/items", headers=[(b"x-tenant-id", b"tenant-a")])

    first = cast(Any, container.resolve(DurableService, module=AppModule, request=request))
    second = cast(Any, container.resolve(DurableService, module=AppModule, request=request))

    assert first is second


def test_durable_scope_isolated_by_context_key(build_request: RequestFactory) -> None:
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
    first_request = build_request(path="/items", headers=[(b"x-tenant-id", b"tenant-a")])
    second_request = build_request(path="/items", headers=[(b"x-tenant-id", b"tenant-b")])

    first = cast(Any, container.resolve(DurableService, module=AppModule, request=first_request))
    second = cast(Any, container.resolve(DurableService, module=AppModule, request=second_request))

    assert first is not second


def test_durable_scope_shares_instances_across_distinct_requests_with_the_same_key(
    build_request: RequestFactory,
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
    first_request = build_request(path="/items", headers=[(b"x-tenant-id", b"tenant-a")])
    second_request = build_request(path="/items", headers=[(b"x-tenant-id", b"tenant-a")])

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
    build_request: RequestFactory,
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
    request = build_request(path="/items", headers=[(b"x-tenant-id", b"tenant-a")])

    with pytest.raises(ProviderResolutionError, match="get_durable_context_key"):
        container.resolve(KeylessDurableService, module=AppModule, request=request)
