"""Unit tests for compiled route contracts."""

from __future__ import annotations

from bustan import (
    APP_GUARD,
    APP_PIPE,
    Controller,
    Get,
    Module,
    UseFilters,
    UseGuards,
    UseInterceptors,
    UsePipes,
)
from bustan.core.ioc.container import build_container
from bustan.core.module.graph import build_module_graph
from bustan.platform.http.compiler import RouteCompiler, compile_route_contracts


def test_route_contracts_include_route_identity_and_ownership() -> None:
    @Controller("/users")
    class UsersController:
        @Get("/{user_id}")
        def read_user(self, user_id: int) -> dict[str, int]:
            return {"user_id": user_id}

    @Module(controllers=[UsersController])
    class AppModule:
        pass

    graph = build_module_graph(AppModule)
    container = build_container(graph)

    [contract] = compile_route_contracts(graph, container)

    assert contract.module_key is AppModule
    assert contract.controller_cls is UsersController
    assert contract.handler_name == "read_user"
    assert contract.method == "GET"
    assert contract.path == "/users/{user_id}"
    assert contract.name == "read_user"


def test_route_contracts_attach_companion_plans_once_in_stable_order() -> None:
    global_guard = object()
    global_pipe = object()
    controller_guard = object()
    handler_guard = object()
    controller_interceptor = object()
    handler_pipe = object()
    handler_filter = object()

    @UseGuards(controller_guard)
    @UseInterceptors(controller_interceptor)
    @Controller("/users")
    class UsersController:
        @UseGuards(handler_guard)
        @UsePipes(handler_pipe)
        @UseFilters(handler_filter)
        @Get("/{user_id}")
        def read_user(self, user_id: int) -> dict[str, int]:
            return {"user_id": user_id}

    @Module(
        controllers=[UsersController],
        providers=[
            {"provide": APP_GUARD, "use_value": global_guard},
            {"provide": APP_PIPE, "use_value": global_pipe},
        ],
    )
    class AppModule:
        pass

    graph = build_module_graph(AppModule)
    container = build_container(graph)

    [contract] = RouteCompiler(graph, container).compile()

    assert contract.binding_plan.handler_name == "read_user"
    assert [binding.name for binding in contract.binding_plan.parameters] == ["user_id"]
    assert contract.pipeline_plan.guards == (global_guard, controller_guard, handler_guard)
    assert contract.pipeline_plan.pipes == (global_pipe, handler_pipe)
    assert contract.pipeline_plan.interceptors == (controller_interceptor,)
    assert contract.pipeline_plan.filters == (handler_filter,)
    assert contract.response_plan is not None
    assert contract.policy_plan.auth is None
    assert contract.policy_plan.roles == ()
    assert contract.policy_plan.permissions == ()


def test_route_contracts_normalize_versions_and_hosts() -> None:
    @Controller("/users", version="1", host="api.example.test")
    class UsersController:
        @Get("/", version=["2", "3"])
        def index(self) -> dict[str, str]:
            return {"status": "ok"}

    @Module(controllers=[UsersController])
    class AppModule:
        pass

    graph = build_module_graph(AppModule)
    container = build_container(graph)

    [contract] = compile_route_contracts(graph, container)

    assert contract.versions == ("2", "3")
    assert contract.hosts == ("api.example.test",)


def test_route_contracts_allow_route_hosts_to_override_controller_hosts() -> None:
    @Controller("/users", hosts=("api.example.test", "admin.example.test"))
    class UsersController:
        @Get("/", hosts=("edge.example.test", "api.example.test"))
        def index(self) -> dict[str, str]:
            return {"status": "ok"}

    @Module(controllers=[UsersController])
    class AppModule:
        pass

    graph = build_module_graph(AppModule)
    container = build_container(graph)

    [contract] = compile_route_contracts(graph, container)

    assert contract.hosts == ("edge.example.test", "api.example.test")