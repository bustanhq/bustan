"""Unit tests for execution-plan compilation."""

from __future__ import annotations

from typing import cast

from starlette.applications import Starlette

from bustan import APP_GUARD, Controller, Get, Guard, Module, create_app
from bustan.kernel.ioc.container import build_container
from bustan.kernel.module.graph import build_module_graph
from bustan.runtime.compiler import GlobalPipelineProvider, compile_route_contracts
from bustan.runtime.execution import _application_runtime, compile_execution_plans


def test_compile_execution_plans_marks_sync_and_async_handlers() -> None:
    @Controller("/users")
    class UsersController:
        @Get("/sync")
        def read_sync(self) -> dict[str, str]:
            return {"kind": "sync"}

        @Get("/async")
        async def read_async(self) -> dict[str, str]:
            return {"kind": "async"}

    @Module(controllers=[UsersController])
    class AppModule:
        pass

    graph = build_module_graph(AppModule)
    container = build_container(graph)

    plans = compile_execution_plans(compile_route_contracts(graph, container))

    assert {plan.handler_name: plan.is_async_handler for plan in plans} == {
        "read_sync": False,
        "read_async": True,
    }


def test_the_application_a_route_runs_under_is_the_bustan_one_however_it_arrives() -> None:
    @Controller("/users")
    class UsersController:
        @Get("/")
        def index(self) -> dict[str, str]:
            return {"status": "ok"}

    @Module(controllers=[UsersController])
    class AppModule:
        pass

    application = create_app(AppModule)
    server = application.get_http_server()
    stranger = Starlette()

    assert _application_runtime(application) is application
    assert _application_runtime(server) is application
    # Nothing to unwrap, so the transport's own object is passed through unchanged.
    assert _application_runtime(stranger) is stranger


def test_a_global_component_only_a_factory_can_build_is_named_by_its_token() -> None:
    def build_guard() -> Guard:
        raise NotImplementedError

    @Controller("/users")
    class UsersController:
        @Get("/")
        def index(self) -> dict[str, str]:
            return {"status": "ok"}

    @Module(
        controllers=[UsersController],
        providers=[{"provide": APP_GUARD, "use_factory": build_guard}],
    )
    class AppModule:
        pass

    graph = build_module_graph(AppModule)
    container = build_container(graph)

    [contract] = compile_route_contracts(graph, container)
    global_guard = cast(GlobalPipelineProvider, contract.pipeline_plan.guards[0])

    assert global_guard.declared_component is None
    assert global_guard.label == "APP_GUARD"
