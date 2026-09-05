"""Unit tests for the controller lifetimes route compilation will accept.

Every test here builds the module graph and then compiles it, which is the sequence a
served application runs. The lifetime refusal itself belongs to the graph, so that a
context and an application read one declaration the same way; these assert that the
composed path an application takes still ends in the same verdict.
"""

from __future__ import annotations

import pytest
from starlette.requests import Request

from bustan import Controller, Get, Module, Scope
from bustan.core.errors import InvalidControllerError
from bustan.core.ioc.container import build_container
from bustan.core.module.graph import build_module_graph
from bustan.platform.http.compiler import RouteContract, compile_route_contracts


def _compile(root_module: type[object]) -> tuple[RouteContract, ...]:
    graph = build_module_graph(root_module)
    return compile_route_contracts(graph, build_container(graph))


@pytest.mark.parametrize("scope", [Scope.SINGLETON, Scope.REQUEST, Scope.TRANSIENT])
def test_compilation_accepts_every_lifetime_a_controller_can_be_served_under(
    scope: Scope,
) -> None:
    @Controller("/tenants", scope=scope)
    class TenantsController:
        @Get("/")
        def list_tenants(self) -> list[str]:
            return ["acme"]

    @Module(controllers=[TenantsController])
    class AppModule:
        pass

    [contract] = _compile(AppModule)

    assert contract.controller_cls is TenantsController


def test_compilation_refuses_a_durable_controller_that_declares_no_context_key_hook() -> None:
    @Controller("/tenants", scope=Scope.DURABLE)
    class TenantsController:
        @Get("/")
        def list_tenants(self) -> list[str]:
            return ["acme"]

    @Module(controllers=[TenantsController])
    class AppModule:
        pass

    with pytest.raises(InvalidControllerError):
        _compile(AppModule)


def test_compilation_refuses_a_durable_controller_that_declares_a_context_key_hook() -> None:
    @Controller("/tenants", scope=Scope.DURABLE)
    class TenantsController:
        @classmethod
        def get_durable_context_key(cls, request: Request | None) -> str | None:
            return request.headers.get("x-tenant") if request is not None else None

        @Get("/")
        def list_tenants(self) -> list[str]:
            return ["acme"]

    @Module(controllers=[TenantsController])
    class AppModule:
        pass

    with pytest.raises(InvalidControllerError):
        _compile(AppModule)


def test_compilation_reads_a_context_key_hook_as_a_hook_rather_than_a_route_method() -> None:
    @Controller("/tenants")
    class TenantsController:
        @classmethod
        def get_durable_context_key(cls, request: Request | None) -> str | None:
            return request.headers.get("x-tenant") if request is not None else None

        @Get("/")
        def list_tenants(self) -> list[str]:
            return ["acme"]

    @Module(controllers=[TenantsController])
    class AppModule:
        pass

    with pytest.raises(InvalidControllerError):
        _compile(AppModule)


def test_compilation_refuses_a_durable_controller_that_declares_no_routes() -> None:
    @Controller("/tenants", scope=Scope.DURABLE)
    class TenantsController:
        pass

    @Module(controllers=[TenantsController])
    class AppModule:
        pass

    with pytest.raises(InvalidControllerError):
        _compile(AppModule)
