"""Unit tests for execution-plan compilation."""

from __future__ import annotations

from bustan import Controller, Get, Module
from bustan.core.ioc.container import build_container
from bustan.core.module.graph import build_module_graph
from bustan.platform.http.compiler import compile_route_contracts
from bustan.platform.http.execution import compile_execution_plans


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
