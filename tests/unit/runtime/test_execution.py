"""Unit tests for execution-plan compilation and the order the request path runs in."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import anyio
import pytest
from starlette.applications import Starlette

from bustan import (
    APP_FILTER,
    APP_GUARD,
    APP_PIPE,
    ApplicationContext,
    Controller,
    ExceptionFilter,
    ExecutionContext,
    Get,
    Guard,
    Injectable,
    Module,
    Pipe,
    Scope,
    UseGuards,
    create_app,
)
from bustan.contracts import HttpRequest
from bustan.errors import GuardRejectedError
from bustan.kernel.ioc.container import Container, build_container
from bustan.kernel.module.graph import build_module_graph
from bustan.observability.correlation import current_correlation_id
from bustan.pipeline.filters import handle_exception
from bustan.runtime.compiler import GlobalPipelineProvider, compile_route_contracts
from bustan.runtime.controller_factory import ControllerFactory
from bustan.runtime.execution import (
    HttpExecutionResult,
    RequestLimitExceptionFilter,
    RequestTimeoutError,
    _application_runtime,
    _with_limit_filter,
    compile_execution_plans,
    execute_http_route,
    request_limits_of,
    set_request_limits,
)
from bustan.runtime.params import RequestBodyTooLargeError, RequestLimits
from bustan.testing import AsgiTestClient

if TYPE_CHECKING:
    from tests.conftest import HttpRequestFactory


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
    context = ApplicationContext(build_container(build_module_graph(AppModule)))
    stranger = Starlette()

    assert _application_runtime(application) is application
    assert _application_runtime(server) is application
    # A context assembled without a server serves no HTTP traffic, but it is still the
    # application a provider resolved through it is running inside.
    assert _application_runtime(context) is context
    # Nothing to unwrap, so the transport's own object is passed through unchanged.
    assert _application_runtime(stranger) is stranger


def test_an_object_that_is_not_a_bustan_application_is_never_taken_for_one() -> None:
    """Everything the unwrapping is handed belongs to someone else until proven otherwise.

    An adapter passes whatever its transport calls the application, and a test passes
    whatever stands in for one. Neither is recognised on a partial resemblance: an
    object that is not an assembled application comes back as itself, so a stranger is
    never seated where providers expect the application, and neither is a stranger a
    transport attached to its own state.
    """

    partial = SimpleNamespace(container=object())
    carrying_a_stranger = SimpleNamespace(state=SimpleNamespace(bustan_application=object()))
    nothing_attached = SimpleNamespace(state=SimpleNamespace())

    assert _application_runtime(partial) is partial
    assert _application_runtime(carrying_a_stranger) is carrying_a_stranger
    assert _application_runtime(nothing_attached) is nothing_attached


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


@pytest.mark.anyio
async def test_a_refusal_leaves_the_durable_partition_a_concurrent_request_created(
    build_http_request: HttpRequestFactory,
) -> None:
    constructions: list[object] = []
    refusal_pending = anyio.Event()
    admitted_partition_built = anyio.Event()

    @Injectable(scope=Scope.DURABLE)
    class RefusedTenantGuard(Guard):
        def __init__(self) -> None:
            constructions.append(object())

        @classmethod
        def get_durable_context_key(cls, request: HttpRequest | None) -> object:
            return request.headers.get("x-tenant") if request is not None else None

        async def can_activate(self, context: ExecutionContext) -> bool:
            # The refusal is held open until the other request has cached a partition
            # of its own, which is the interleaving this test is about: the second
            # partition appears after the first request began deciding.
            refusal_pending.set()
            await admitted_partition_built.wait()
            return False

    @Injectable(scope=Scope.DURABLE)
    class TenantPool:
        @classmethod
        def get_durable_context_key(cls, request: HttpRequest | None) -> object:
            return request.headers.get("x-tenant") if request is not None else None

    class AdmitOnceTheRefusalIsPending(Guard):
        async def can_activate(self, context: ExecutionContext) -> bool:
            await refusal_pending.wait()
            return True

    @Controller("/refused")
    class RefusedController:
        @UseGuards(RefusedTenantGuard)
        @Get("/")
        def read(self) -> dict[str, str]:
            return {"status": "never reached"}

    @Controller("/admitted", scope=Scope.REQUEST)
    class AdmittedController:
        def __init__(self, pool: TenantPool) -> None:
            self._pool = pool

        @UseGuards(AdmitOnceTheRefusalIsPending())
        @Get("/")
        async def read(self) -> dict[str, str]:
            admitted_partition_built.set()
            return {"status": "ok"}

    @Module(
        controllers=[RefusedController, AdmittedController],
        providers=[RefusedTenantGuard, TenantPool],
    )
    class AppModule:
        pass

    graph = build_module_graph(AppModule)
    container = build_container(graph)
    factory = ControllerFactory(container)
    plans = {
        plan.controller_cls: plan
        for plan in compile_execution_plans(compile_route_contracts(graph, container))
    }
    results: dict[str, HttpExecutionResult] = {}

    async def serve(name: str, controller_cls: type[object], tenant: bytes) -> None:
        results[name] = await execute_http_route(
            application_runtime=None,
            container=container,
            factory=factory,
            execution_plan=plans[controller_cls],
            request=build_http_request(
                path=plans[controller_cls].path,
                headers=[(b"x-tenant", tenant)],
            ),
        )

    # A deadline, because each request waits on the other and a regression that stops
    # one of them from getting there would otherwise hang the suite rather than fail.
    with anyio.fail_after(5):
        async with anyio.create_task_group() as requests:
            requests.start_soon(serve, "refused", RefusedController, b"refused-corp")
            requests.start_soon(serve, "admitted", AdmittedController, b"admitted-corp")

    partitions = [key[2] for key in container.scope_manager.durable_instances]

    assert isinstance(results["refused"].error, GuardRejectedError)
    assert results["admitted"].error is None
    # The refusal built its own partition and undid it.
    assert len(constructions) == 1
    assert "refused-corp" not in partitions
    # And left alone the one the other request created while it was deciding.
    assert "admitted-corp" in partitions


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


def test_request_limits_default_when_an_application_declares_none() -> None:
    @Controller("/users")
    class UsersController:
        @Get("/")
        def index(self) -> dict[str, str]:
            return {"status": "ok"}

    @Module(controllers=[UsersController])
    class AppModule:
        pass

    application = create_app(AppModule)

    assert request_limits_of(application) == RequestLimits()


def test_request_limits_are_read_back_from_the_application_they_were_set_on() -> None:
    # The limits belong to an application rather than to the process, and they are read
    # back through whatever the transport hands over, which is the server rather than
    # the application on the served path.
    @Controller("/users")
    class UsersController:
        @Get("/")
        def index(self) -> dict[str, str]:
            return {"status": "ok"}

    @Module(controllers=[UsersController])
    class AppModule:
        pass

    application = create_app(AppModule)
    limits = RequestLimits(max_body_bytes=64, timeout_seconds=0.5, sync_handler_threads=3)
    set_request_limits(application, limits)

    assert request_limits_of(application) is limits
    assert request_limits_of(application.get_http_server()) is limits


def test_the_limit_filter_answers_an_oversized_body_with_413() -> None:
    context = cast(Any, SimpleNamespace(request=SimpleNamespace(path="/uploads")))
    error = RequestBodyTooLargeError("The request body declares 9 bytes, over the 4 byte limit")

    response = anyio.run(RequestLimitExceptionFilter().catch, error, context)

    assert response is not None
    assert response.status_code == 413
    assert response.media_type == "application/problem+json"
    assert json.loads(response.body) == {
        "type": "about:blank",
        "title": "Content Too Large",
        "status": 413,
        "detail": "The request body declares 9 bytes, over the 4 byte limit",
        "instance": "/uploads",
    }


def test_the_limit_filter_answers_a_timeout_with_504_and_no_configured_budget() -> None:
    # The message names the budget the deployment chose, which is how long a caller
    # would have to hold a connection to occupy a worker. The status's own reason is
    # what the caller is told instead.
    context = cast(Any, SimpleNamespace(request=SimpleNamespace(path="/slow")))
    error = RequestTimeoutError("The request exceeded the 0.25 second limit")

    response = anyio.run(RequestLimitExceptionFilter().catch, error, context)

    assert response is not None
    assert response.status_code == 504
    assert json.loads(response.body) == {
        "type": "about:blank",
        "title": "Gateway Timeout",
        "status": 504,
        "detail": "Gateway Timeout",
        "instance": "/slow",
    }


def test_the_limit_filter_leaves_every_other_exception_to_the_rest_of_the_chain() -> None:
    context = cast(Any, SimpleNamespace(request=SimpleNamespace(path="/anything")))

    assert anyio.run(RequestLimitExceptionFilter().catch, RuntimeError("boom"), context) is None


def test_the_limit_filter_is_offered_the_exception_after_the_applications_own() -> None:
    # Placed first is offered last: the chain prefers a later-declared filter over an
    # earlier one of the same breadth, so an application never loses control of how its
    # own timeouts are rendered by the framework having an answer of its own.
    class ApplicationFilter(ExceptionFilter):
        exception_types = (Exception,)

        async def catch(self, exc: Exception, context: ExecutionContext) -> object:
            return {"detail": "mine"}

    application_filter = ApplicationFilter()
    chain = _with_limit_filter((application_filter,))

    assert chain[0] is not application_filter
    assert isinstance(chain[0], RequestLimitExceptionFilter)
    context = cast(Any, SimpleNamespace(request=SimpleNamespace(path="/slow")))
    result = anyio.run(
        handle_exception,
        context,
        RequestTimeoutError("The request exceeded the 0.25 second limit"),
        chain,
    )

    assert result == {"detail": "mine"}


def test_the_request_entry_point_names_the_request_and_releases_the_name() -> None:
    """Correlation is bound around the whole request and unbound when it is over.

    The binding is what every log record and every span the request produces reads,
    so it has to be in place before a middleware runs and gone once the outermost one
    has returned; a binding that outlived a request would name the next one wrongly.
    """

    seen: list[str | None] = []

    @Controller("/orders")
    class OrdersController:
        @Get("/")
        def read(self) -> dict[str, str]:
            seen.append(current_correlation_id())
            return {"status": "ok"}

    @Module(controllers=[OrdersController])
    class AppModule:
        pass

    with AsgiTestClient(cast(Any, create_app(AppModule))) as client:
        response = client.get("/orders", headers={"x-correlation-id": "req-42"})

    assert response.status_code == 200
    assert seen == ["req-42"]
    assert current_correlation_id() is None


def _counting_resolutions(container: Container, resolutions: list[object]) -> None:
    """Record every token the container is asked to resolve, and answer as before."""

    resolve_async = container.resolve_async
    resolve = container.resolve

    async def counted_async(token: object, *, module: Any, request: Any = None) -> object:
        resolutions.append(token)
        return await resolve_async(token, module=module, request=request)

    def counted(token: object, *, module: Any, request: Any = None) -> object:
        resolutions.append(token)
        return resolve(token, module=module, request=request)

    counting = cast(Any, container)
    counting.resolve_async = counted_async
    counting.resolve = counted


def test_a_settled_pipeline_is_resolved_from_the_container_once_and_never_again() -> None:
    ran: list[str] = []

    class NoopPipe(Pipe):
        def transform(self, value: object, context: ExecutionContext) -> object:
            ran.append("pipe")
            return value

    @Injectable
    class FirstGuard(Guard):
        def can_activate(self, context: ExecutionContext) -> bool:
            ran.append("first-guard")
            return True

    @Injectable
    class SecondGuard(Guard):
        def can_activate(self, context: ExecutionContext) -> bool:
            ran.append("second-guard")
            return True

    class NeverCatches(ExceptionFilter):
        exception_types = (RuntimeError,)

        async def catch(self, exc: Exception, context: ExecutionContext) -> None:
            return None

    @Controller("/users")
    class UsersController:
        @UseGuards(FirstGuard, SecondGuard)
        @Get("/{name}")
        def read(self, name: str) -> dict[str, str]:
            return {"name": name}

    @Module(
        controllers=[UsersController],
        providers=[
            FirstGuard,
            SecondGuard,
            {"provide": APP_PIPE, "use_class": NoopPipe},
            {"provide": APP_FILTER, "use_class": NeverCatches},
        ],
    )
    class AppModule:
        pass

    application = create_app(AppModule)
    resolutions: list[object] = []
    _counting_resolutions(application.container, resolutions)

    with AsgiTestClient(cast(Any, application)) as client:
        # What starting the application resolved is not what this is counting.
        resolutions.clear()
        first = client.get("/users/ada")
        first_count = len(resolutions)
        ran.clear()
        resolutions.clear()
        second = client.get("/users/ada")

    assert first.json() == {"name": "ada"} == second.json()
    # A global pipe, two guards and a filter: four resolutions the first request pays
    # for, and none any request after it does.
    assert first_count == 4
    assert resolutions == []
    # The components still run; only the asking for them stopped.
    assert ran == ["first-guard", "second-guard", "pipe"]


def test_a_pipeline_component_scoped_to_the_request_is_resolved_for_every_request() -> None:
    # Only what cannot come out differently for the next request is kept. A guard with
    # a lifetime of one request is a different guard for each of them, so it is
    # resolved again every time however often the route is served.
    constructions: list[object] = []

    @Injectable(scope=Scope.REQUEST)
    class RequestScopedGuard(Guard):
        def __init__(self) -> None:
            constructions.append(object())

        def can_activate(self, context: ExecutionContext) -> bool:
            return True

    @Controller("/users")
    class UsersController:
        @UseGuards(RequestScopedGuard)
        @Get("/")
        def read(self) -> dict[str, str]:
            return {"status": "ok"}

    @Module(controllers=[UsersController], providers=[RequestScopedGuard])
    class AppModule:
        pass

    with AsgiTestClient(cast(Any, create_app(AppModule))) as client:
        constructions.clear()
        assert client.get("/users/").status_code == 200
        assert client.get("/users/").status_code == 200

    assert len(constructions) == 2


def test_a_pipeline_kept_from_one_run_is_dropped_when_the_application_starts_again() -> None:
    # A shutdown destroys every instance the container built and the next startup
    # builds a fresh set. What a route kept from the previous run belongs to instances
    # that no longer exist, so it is dropped rather than served.
    seen: list[object] = []

    @Injectable
    class RecordingGuard(Guard):
        def can_activate(self, context: ExecutionContext) -> bool:
            seen.append(self)
            return True

    @Controller("/users")
    class UsersController:
        @UseGuards(RecordingGuard)
        @Get("/")
        def read(self) -> dict[str, str]:
            return {"status": "ok"}

    @Module(controllers=[UsersController], providers=[RecordingGuard])
    class AppModule:
        pass

    application = create_app(AppModule)
    with AsgiTestClient(cast(Any, application)) as client:
        assert client.get("/users/").status_code == 200
    with AsgiTestClient(cast(Any, application)) as client:
        assert client.get("/users/").status_code == 200

    assert len(seen) == 2
    assert seen[0] is not seen[1]
