"""Unit tests for execution-plan compilation and the order the request path runs in."""

from __future__ import annotations

from typing import Any, cast

from starlette.applications import Starlette

from bustan import (
    APP_GUARD,
    Controller,
    ExecutionContext,
    Get,
    Guard,
    Injectable,
    Module,
    Scope,
    UseGuards,
    create_app,
)
from bustan.contracts import HttpRequest
from bustan.kernel.ioc.container import build_container
from bustan.kernel.module.graph import build_module_graph
from bustan.runtime.compiler import GlobalPipelineProvider, compile_route_contracts
from bustan.runtime.execution import _application_runtime, compile_execution_plans
from bustan.testing import AsgiTestClient


class AllowEveryone(Guard):
    def can_activate(self, context: ExecutionContext) -> bool:
        return True


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


def test_a_request_a_guard_refuses_builds_no_request_scoped_or_durable_provider() -> None:
    constructions: list[str] = []

    class DenyEveryone(Guard):
        def can_activate(self, context: ExecutionContext) -> bool:
            return False

    @Injectable(scope=Scope.REQUEST)
    class RequestScopedService:
        def __init__(self) -> None:
            constructions.append("request-scoped")

    @Injectable(scope=Scope.DURABLE)
    class TenantPool:
        def __init__(self) -> None:
            constructions.append("durable")

        @classmethod
        def get_durable_context_key(cls, request: HttpRequest | None) -> object:
            return request.headers.get("x-tenant") if request is not None else None

    @Controller("/tenant", scope=Scope.REQUEST)
    class TenantController:
        def __init__(self, service: RequestScopedService, pool: TenantPool) -> None:
            self._service = service
            self._pool = pool

        @UseGuards(DenyEveryone())
        @Get("/")
        def read(self) -> dict[str, str]:
            return {"status": "never reached"}

    @Module(controllers=[TenantController], providers=[RequestScopedService, TenantPool])
    class AppModule:
        pass

    application = create_app(AppModule)
    scope_manager = application.container.scope_manager
    with AsgiTestClient(cast(Any, application)) as client:
        # Whatever starting the application built is not what this request is about.
        constructions.clear()
        response = client.get("/tenant/", headers={"x-tenant": "acme"})
        partitions = [key[2] for key in scope_manager.durable_instances]

    assert response.status_code == 403
    # A counter, not a reading of the code: the refused caller ran neither constructor.
    assert constructions == []
    assert "acme" not in partitions


def test_a_durable_partition_a_refused_request_named_is_not_left_in_the_cache() -> None:
    constructions: list[object] = []

    @Injectable(scope=Scope.DURABLE)
    class TenantGuard(Guard):
        def __init__(self) -> None:
            constructions.append(object())

        @classmethod
        def get_durable_context_key(cls, request: HttpRequest | None) -> object:
            return request.headers.get("x-tenant") if request is not None else None

        def can_activate(self, context: ExecutionContext) -> bool:
            return False

    @Controller("/tenant")
    class TenantController:
        @UseGuards(TenantGuard)
        @Get("/")
        def read(self) -> dict[str, str]:
            return {"status": "never reached"}

    @Module(controllers=[TenantController], providers=[TenantGuard])
    class AppModule:
        pass

    application = create_app(AppModule)
    scope_manager = application.container.scope_manager
    with AsgiTestClient(cast(Any, application)) as client:
        constructions.clear()
        response = client.get("/tenant/", headers={"x-tenant": "victim-corp"})
        partitions = [key[2] for key in scope_manager.durable_instances]

    assert response.status_code == 403
    # The partition was really created and really dropped again, rather than never
    # having been built: the guard the refusal came from is itself the durable one.
    assert len(constructions) == 1
    assert "victim-corp" not in partitions


def test_a_request_that_is_served_keeps_the_durable_partitions_it_created() -> None:
    @Injectable(scope=Scope.DURABLE)
    class TenantPool:
        @classmethod
        def get_durable_context_key(cls, request: HttpRequest | None) -> object:
            return request.headers.get("x-tenant") if request is not None else None

    @Controller("/tenant", scope=Scope.REQUEST)
    class TenantController:
        def __init__(self, pool: TenantPool) -> None:
            self._pool = pool

        @UseGuards(AllowEveryone())
        @Get("/")
        def read(self) -> dict[str, str]:
            return {"status": "ok"}

    @Module(controllers=[TenantController], providers=[TenantPool])
    class AppModule:
        pass

    application = create_app(AppModule)
    scope_manager = application.container.scope_manager
    with AsgiTestClient(cast(Any, application)) as client:
        response = client.get("/tenant/", headers={"x-tenant": "acme"})
        partitions = [key[2] for key in scope_manager.durable_instances]

    assert response.status_code == 200
    assert "acme" in partitions


def test_guards_run_before_the_controller_and_its_providers_are_constructed() -> None:
    events: list[str] = []

    class RecordingGuard(Guard):
        def can_activate(self, context: ExecutionContext) -> bool:
            events.append("guard")
            return True

    @Injectable(scope=Scope.REQUEST)
    class RequestScopedService:
        def __init__(self) -> None:
            events.append("provider")

    @Controller("/orders", scope=Scope.REQUEST)
    class OrdersController:
        def __init__(self, service: RequestScopedService) -> None:
            events.append("controller")

        @UseGuards(RecordingGuard())
        @Get("/")
        def read(self) -> dict[str, str]:
            events.append("handler")
            return {"status": "ok"}

    @Module(controllers=[OrdersController], providers=[RequestScopedService])
    class AppModule:
        pass

    with AsgiTestClient(cast(Any, create_app(AppModule))) as client:
        events.clear()
        response = client.get("/orders/")

    assert response.status_code == 200
    assert events == ["guard", "provider", "controller", "handler"]
