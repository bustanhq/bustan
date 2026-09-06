"""Unit tests for compiled route contracts."""

from __future__ import annotations

from typing import cast

import pytest

from bustan import (
    APP_GUARD,
    APP_INTERCEPTOR,
    APP_PIPE,
    Controller,
    ExecutionContext,
    Get,
    HttpResponse,
    Interceptor,
    Module,
    UseFilters,
    UseGuards,
    UseInterceptors,
    UsePipes,
)
from bustan.kernel.errors import RouteDefinitionError
from bustan.kernel.ioc.container import build_container
from bustan.kernel.module.graph import build_module_graph
from bustan.pipeline.interceptors import CallHandler
from bustan.runtime.compiler import (
    GlobalPipelineProvider,
    ResponseStrategy,
    RouteCompiler,
    compile_route_contracts,
)


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
    # A global component is carried as the reference the runtime resolves per request,
    # ahead of everything the controller and the handler declared.
    assert contract.pipeline_plan.guards == (
        GlobalPipelineProvider(APP_GUARD, AppModule, global_guard),
        controller_guard,
        handler_guard,
    )
    assert contract.pipeline_plan.pipes == (
        GlobalPipelineProvider(APP_PIPE, AppModule, global_pipe),
        handler_pipe,
    )
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


def test_route_contracts_resolve_stringified_return_annotations_for_response_strategies() -> None:
    @Controller("/users")
    class UsersController:
        @Get("/")
        def index(self) -> HttpResponse:
            return HttpResponse.json({"status": "ok"})

    @Module(controllers=[UsersController])
    class AppModule:
        pass

    graph = build_module_graph(AppModule)
    container = build_container(graph)

    [contract] = compile_route_contracts(graph, container)

    assert contract.response_plan.strategy is ResponseStrategy.RAW


def test_global_pipeline_components_are_named_rather_than_built_while_routes_compile() -> None:
    built: list[str] = []

    class CountingGuard:
        def __init__(self) -> None:
            built.append("guard")

    @Controller("/users")
    class UsersController:
        @Get("/")
        def index(self) -> dict[str, str]:
            return {"status": "ok"}

    @Module(
        controllers=[UsersController],
        providers=[{"provide": APP_GUARD, "use_class": CountingGuard}],
    )
    class AppModule:
        pass

    graph = build_module_graph(AppModule)
    container = build_container(graph)

    [contract] = compile_route_contracts(graph, container)

    assert built == []
    assert contract.pipeline_plan.guards == (
        GlobalPipelineProvider(APP_GUARD, AppModule, CountingGuard),
    )
    global_guard = cast(GlobalPipelineProvider, contract.pipeline_plan.guards[0])
    assert global_guard.label == "CountingGuard"


def test_a_global_interceptor_that_mutates_the_body_is_refused_on_a_raw_route() -> None:
    class BodyRewritingInterceptor(Interceptor):
        mutates_response_body = True

        async def intercept(self, context: ExecutionContext, next: CallHandler) -> object:
            raise NotImplementedError

    @Controller("/raw")
    class RawController:
        @Get("/")
        def index(self) -> HttpResponse:
            return HttpResponse.json({"status": "ok"})

    @Module(
        controllers=[RawController],
        providers=[{"provide": APP_INTERCEPTOR, "use_value": [BodyRewritingInterceptor()]}],
    )
    class ListBoundModule:
        pass

    @Module(
        controllers=[RawController],
        providers=[{"provide": APP_INTERCEPTOR, "use_class": BodyRewritingInterceptor}],
    )
    class ClassBoundModule:
        pass

    for module in (ListBoundModule, ClassBoundModule):
        graph = build_module_graph(module)
        container = build_container(graph)

        with pytest.raises(RouteDefinitionError, match="BodyRewritingInterceptor"):
            compile_route_contracts(graph, container)
