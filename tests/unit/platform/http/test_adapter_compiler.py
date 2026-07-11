"""Unit tests for adapter-route compilation."""

from __future__ import annotations

from bustan import Controller, Get, Module, VERSION_NEUTRAL, VersioningOptions, VersioningType
from bustan.core.ioc.container import build_container
from bustan.core.module.graph import build_module_graph
from bustan.platform.http.adapter import CompiledAdapterRoute, compile_adapter_routes
from bustan.platform.http.adapters.starlette_adapter import StarletteAdapter
from bustan.platform.http.compiler import compile_route_contracts
from bustan.platform.http.execution import ExecutionPlan


def test_adapter_compiler_consumes_compiled_route_contracts_only() -> None:
    @Controller("/users")
    class UsersController:
        @Get("/")
        def index(self) -> dict[str, str]:
            return {"status": "ok"}

    @Module(controllers=[UsersController])
    class AppModule:
        pass

    graph = build_module_graph(AppModule)
    container = build_container(graph)
    route_contracts = compile_route_contracts(graph, container)

    compiled_routes = compile_adapter_routes(
        StarletteAdapter(),
        route_contracts,
        container,
    )

    assert len(compiled_routes) == 1
    assert isinstance(compiled_routes[0], CompiledAdapterRoute)
    assert compiled_routes[0].contracts == (route_contracts[0],)
    assert len(compiled_routes[0].execution_plans) == 1
    assert isinstance(compiled_routes[0].execution_plans[0], ExecutionPlan)
    assert compiled_routes[0].execution_plans[0].route_contract is route_contracts[0]
    assert compiled_routes[0].path == "/users"
    assert compiled_routes[0].methods == ("GET",)


def test_adapter_compiler_preserves_deterministic_order() -> None:
    @Controller("/zeta")
    class ZetaController:
        @Get("/")
        def index(self) -> dict[str, str]:
            return {"controller": "zeta"}

    @Controller("/alpha")
    class AlphaController:
        @Get("/")
        def index(self) -> dict[str, str]:
            return {"controller": "alpha"}

    @Module(controllers=[ZetaController, AlphaController])
    class AppModule:
        pass

    graph = build_module_graph(AppModule)
    container = build_container(graph)
    compiled_routes = compile_adapter_routes(
        StarletteAdapter(),
        compile_route_contracts(graph, container),
        container,
    )

    assert [compiled_route.path for compiled_route in compiled_routes] == ["/zeta", "/alpha"]


def test_adapter_compiler_keeps_adapter_registration_data_behind_the_boundary() -> None:
    @Controller("/users", version=VERSION_NEUTRAL)
    class UsersController:
        @Get("/")
        def index(self) -> dict[str, str]:
            return {"status": "ok"}

    @Module(controllers=[UsersController])
    class AppModule:
        pass

    graph = build_module_graph(AppModule)
    container = build_container(graph)
    compiled_routes = compile_adapter_routes(
        StarletteAdapter(),
        compile_route_contracts(graph, container),
        container,
        versioning=VersioningOptions(type=VersioningType.HEADER),
    )

    assert compiled_routes[0].registration is not None
    assert compiled_routes[0].contracts[0].controller_cls is UsersController