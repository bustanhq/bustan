"""Unit tests for execution-plan compilation and the order the request path runs in."""

from __future__ import annotations

import inspect
import itertools
import json
from collections import Counter
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
    BadRequestException,
    CallHandler,
    ClassProvider,
    Controller,
    DefaultResponseSerializer,
    ExceptionFilter,
    ExecutionContext,
    FactoryProvider,
    Get,
    Guard,
    HttpResponse,
    Injectable,
    Interceptor,
    Middleware,
    MiddlewareConsumer,
    Module,
    Pipe,
    Post,
    Scope,
    UseFilters,
    UseGuards,
    UseInterceptors,
    UsePipes,
    create_app,
)
from bustan.contracts import ApplicationRuntime, HttpRequest
from bustan.errors import GuardRejectedError
from bustan.kernel.errors import MethodNotAllowedException, NotFoundException
from bustan.kernel.ioc.container import Container, build_container
from bustan.kernel.module.graph import build_module_graph
from bustan.observability.correlation import current_correlation_id
from bustan.observability.observability import ObservabilityHooks
from bustan.pipeline.filters import handle_exception
from bustan.runtime import execution
from bustan.runtime.compiler import GlobalPipelineProvider, compile_route_contracts
from bustan.runtime.controller_factory import ControllerFactory
from bustan.runtime.execution import (
    HttpExecutionResult,
    RequestLimitExceptionFilter,
    RequestTimeoutError,
    _application_runtime,
    _is_application,
    _with_limit_filter,
    compile_execution_plans,
    execute_http_route,
    method_not_allowed_response,
    not_found_response,
    observability_hooks_of,
    request_limits_of,
    response_handler_of,
    set_observability_hooks,
    set_request_limits,
    set_response_serializer,
)
from bustan.runtime.params import RequestBodyTooLargeError, RequestLimits
from bustan.testing import AsgiTestClient

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from bustan.kernel.ioc.scopes import DurableKey
    from tests.conftest import HttpRequestFactory


class AllowEveryone(Guard):
    def can_activate(self, context: ExecutionContext) -> bool:
        return True


class RecordingMetrics:
    """A metric sink keeping the status of every request it is told about."""

    def __init__(self) -> None:
        self.statuses: list[str] = []

    def record_request(self, *, labels: Mapping[str, str], duration_seconds: float) -> None:
        self.statuses.append(labels["status"])


class Envelope:
    """Write what a handler returns inside an envelope naming the application.

    Anything else, such as the response a refusal is rendered as, is written the default
    way, so an envelope appears only where a handler's return value was serialized.
    """

    def __init__(self, name: str) -> None:
        self._name = name
        self._default = DefaultResponseSerializer()

    def serialize(self, value: object) -> HttpResponse:
        if isinstance(value, dict):
            return HttpResponse.json({"envelope": self._name, "data": value})
        return cast(HttpResponse, self._default.serialize(value))


class RefuseEveryRequest(Middleware):
    """Refuse the request before the route it fronts is entered."""

    async def use(self, request: HttpRequest, call_next: Any) -> Any:
        raise BadRequestException("refused before the route")


def _notes_module() -> type[object]:
    """Return a module whose routes take each path a request can take through the runtime.

    ``GET /notes`` returns a value, ``POST /notes`` binds a body read under the
    application's limits, ``GET /notes/broken`` fails inside its handler, and
    ``GET /refused`` is refused by a middleware before its route is entered. Each call
    builds new classes, so two applications never share a module.
    """

    @Controller("/notes")
    class NotesController:
        @Get("/")
        async def read(self) -> dict[str, str]:
            return {"title": "a note"}

        @Post("/")
        async def create(self, title: str) -> dict[str, str]:
            return {"title": title}

        @Get("/broken")
        async def broken(self) -> dict[str, str]:
            raise RuntimeError("the handler failed")

    @Controller("/refused")
    class RefusedController:
        @Get("/")
        async def read(self) -> dict[str, str]:
            return {"status": "never reached"}

    @Module(controllers=[NotesController, RefusedController])
    class NotesModule:
        def configure(self, consumer: MiddlewareConsumer) -> None:
            consumer.apply(RefuseEveryRequest).for_routes("/refused*")

    return NotesModule


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


def test_each_object_is_recognised_by_what_it_carries_as_the_protocol_recognises_it() -> None:
    """What a class declares is read once per type, and whatever it leaves out from each object.

    Each candidate sits beside an object of the same type that is answered the other way,
    and the list is judged forwards and then backwards, so the first object of a type
    never decides for the next. ``ApplicationRuntime``'s own check is the reference.
    """

    class HalfDeclared:
        # The class declares one member and leaves the other to each instance.
        def __init__(self, *, carries_module_graph: bool) -> None:
            if carries_module_graph:
                self.module_graph = object()

        @property
        def container(self) -> object:
            return object()

    class Slotted:
        # A slot is declared on the class, so every instance carries both members.
        __slots__ = ("container", "module_graph")

    application = create_app(_notes_module())
    candidates = [
        application,
        application.get_http_server(),
        ApplicationContext(application.container),
        Starlette(),
        SimpleNamespace(container=object(), module_graph=object()),
        SimpleNamespace(container=object()),
        HalfDeclared(carries_module_graph=True),
        HalfDeclared(carries_module_graph=False),
        Slotted(),
        object(),
        None,
    ]
    judged = [*candidates, *reversed(candidates)]

    verdicts = [_is_application(candidate) for candidate in judged]

    assert verdicts == [isinstance(candidate, ApplicationRuntime) for candidate in judged]
    assert verdicts[: len(candidates)] == [
        True,
        False,
        True,
        False,
        True,
        False,
        True,
        False,
        True,
        False,
        False,
    ]


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
        providers=[FactoryProvider(provide=APP_GUARD, use_factory=build_guard)],
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
    with AsgiTestClient(cast(Any, application)) as client:
        # Whatever starting the application built is not what this request is about.
        constructions.clear()
        response = client.get("/tenant/", headers={"x-tenant": "acme"})
        partitions = [
            cast("DurableKey", key)[2] for key in application.container.durable_instance_view
        ]

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
    with AsgiTestClient(cast(Any, application)) as client:
        constructions.clear()
        response = client.get("/tenant/", headers={"x-tenant": "victim-corp"})
        partitions = [
            cast("DurableKey", key)[2] for key in application.container.durable_instance_view
        ]

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
    with AsgiTestClient(cast(Any, application)) as client:
        response = client.get("/tenant/", headers={"x-tenant": "acme"})
        partitions = [
            cast("DurableKey", key)[2] for key in application.container.durable_instance_view
        ]

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

    partitions = [cast("DurableKey", key)[2] for key in container.durable_instance_view]

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


# The stages a route may declare. The order test below turns each of them on and off.
_STAGES = ("middleware", "guard", "pipe", "interceptor", "parameter", "filter")


class _HandlerFailed(LookupError):
    """Raised by a handler a test has asked to fail."""


def _staged_module(stages: frozenset[str], events: list[str], *, fails: bool) -> type[object]:
    """Return a module whose routes declare exactly *stages*, each recording itself as it runs.

    ``GET /items/named`` binds one parameter and ``GET /items/plain`` binds none. Every
    other stage is declared on the controller, so both routes carry it. The controller is
    request-scoped, so building it is recorded for every request.
    """

    class RecordingMiddleware(Middleware):
        async def use(self, request: HttpRequest, call_next: Any) -> Any:
            events.append("middleware:before")
            response = await call_next(request)
            events.append("middleware:after")
            return response

    class RecordingGuard(Guard):
        def can_activate(self, context: ExecutionContext) -> bool:
            events.append("guard")
            return True

    class RecordingPipe(Pipe):
        def transform(self, value: object, context: ExecutionContext) -> object:
            events.append("pipe")
            return value

    class RecordingInterceptor(Interceptor):
        async def intercept(self, context: ExecutionContext, next: CallHandler) -> object:
            events.append("interceptor:before")
            result = await next.handle()
            events.append("interceptor:after")
            return result

    class RecordingFilter(ExceptionFilter):
        exception_types = (_HandlerFailed,)

        def catch(self, exc: Exception, context: ExecutionContext) -> object:
            events.append("filter")
            return HttpResponse.json({"handled": True}, status_code=418)

    def answer() -> dict[str, str]:
        events.append("handler")
        if fails:
            raise _HandlerFailed("the handler failed")
        return {"status": "ok"}

    @Controller("/items", scope=Scope.REQUEST)
    class ItemsController:
        def __init__(self) -> None:
            events.append("controller")

        @Get("/named")
        async def named(self, name: str) -> dict[str, str]:
            return answer()

        @Get("/plain")
        async def plain(self) -> dict[str, str]:
            return answer()

    declarations = {
        "guard": UseGuards(RecordingGuard()),
        "pipe": UsePipes(RecordingPipe()),
        "interceptor": UseInterceptors(RecordingInterceptor()),
        "filter": UseFilters(RecordingFilter()),
    }
    for stage, declare in declarations.items():
        if stage in stages:
            declare(ItemsController)

    class StagedModule:
        def configure(self, consumer: MiddlewareConsumer) -> None:
            if "middleware" in stages:
                consumer.apply(RecordingMiddleware).for_routes("/items*")

    return Module(controllers=[ItemsController])(StagedModule)


def _expected_events(stages: frozenset[str], *, fails: bool) -> list[str]:
    """Return the order one request runs the stages of a route declaring *stages* in."""

    events = ["middleware:before"] if "middleware" in stages else []
    if "guard" in stages:
        events.append("guard")
    events.append("controller")
    if {"pipe", "parameter"} <= stages:
        events.append("pipe")
    if "interceptor" in stages:
        events.append("interceptor:before")
    events.append("handler")
    if fails and "filter" in stages:
        events.append("filter")
    if not fails and "interceptor" in stages:
        events.append("interceptor:after")
    if "middleware" in stages:
        events.append("middleware:after")
    return events


def test_every_combination_of_declared_stages_runs_in_one_order() -> None:
    """Whichever stages a route declares, the ones it declares run in the same order.

    Every combination of middleware, a guard, a pipe, an interceptor, a bound parameter
    and a filter is served once and failed once. A route leaving a stage out runs the
    rest exactly as a route declaring all of them does, and a failure is answered by the
    filter after the handler and before the middleware returns.
    """

    mismatches: list[tuple[list[str], bool, int, list[str]]] = []
    for size in range(len(_STAGES) + 1):
        for chosen in itertools.combinations(_STAGES, size):
            stages = frozenset(chosen)
            for fails in (False, True):
                events: list[str] = []
                path = "/items/named?name=ada" if "parameter" in stages else "/items/plain"
                with AsgiTestClient(
                    cast(Any, create_app(_staged_module(stages, events, fails=fails)))
                ) as client:
                    events.clear()
                    status = client.get(path).status_code
                expected_status = (418 if "filter" in stages else 500) if fails else 200
                if (status, events) != (expected_status, _expected_events(stages, fails=fails)):
                    mismatches.append((sorted(stages), fails, status, events))

    assert mismatches == []


def _counted(calls: Counter[str], name: str, function: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap *function* so that every call to it is tallied under *name*."""

    if inspect.iscoroutinefunction(function):

        async def counted_coroutine(*args: Any, **kwargs: Any) -> Any:
            calls[name] += 1
            return await function(*args, **kwargs)

        return counted_coroutine

    def counted(*args: Any, **kwargs: Any) -> Any:
        calls[name] += 1
        return function(*args, **kwargs)

    return counted


def test_a_route_enters_no_stage_it_does_not_declare(monkeypatch: pytest.MonkeyPatch) -> None:
    """A stage a route does not declare costs its requests nothing, not even an empty pass.

    The first route declares no middleware, guard, pipe, interceptor or parameter, so no
    execution context is built for it and neither chain is entered. The second binds one
    parameter that nothing transforms, so binding is the only stage it enters.
    """

    @Controller("/bare")
    class BareController:
        @Get("/")
        async def read(self) -> dict[str, str]:
            return {"status": "ok"}

    @Controller("/items")
    class ItemsController:
        @Get("/{item_id}")
        async def read(self, item_id: int) -> dict[str, int]:
            return {"item_id": item_id}

    @Module(controllers=[BareController, ItemsController])
    class AppModule:
        pass

    calls: Counter[str] = Counter()
    with AsgiTestClient(cast(Any, create_app(AppModule))) as client:
        # What a route builds for its first request is not what a request costs it.
        assert client.get("/bare").status_code == 200
        assert client.get("/items/7").status_code == 200
        for name in (
            "run_middleware_chain",
            "run_guards",
            "bind_handler_parameters",
            "run_pipes",
            "call_with_interceptors",
        ):
            monkeypatch.setattr(execution, name, _counted(calls, name, getattr(execution, name)))
        monkeypatch.setattr(
            ExecutionContext,
            "__init__",
            _counted(calls, "ExecutionContext", ExecutionContext.__init__),
        )
        monkeypatch.setattr(
            ControllerFactory,
            "resolve_pipeline_async",
            _counted(calls, "resolve_pipeline_async", ControllerFactory.resolve_pipeline_async),
        )
        assert client.get("/bare").json() == {"status": "ok"}
        bare = dict(calls)
        calls.clear()
        assert client.get("/items/7").json() == {"item_id": 7}
        items = dict(calls)

    assert bare == {}
    assert items == {"bind_handler_parameters": 1}


def test_a_failure_while_answering_a_failure_is_answered_on_a_route_with_no_middleware() -> None:
    """What escapes a route with no middleware is still answered by the error model.

    A filter that answers with a value no response can be written from fails while the
    first failure is being answered, and that second failure leaves the route itself. The
    entry point answers it, as it answers one escaping a middleware, rather than letting
    it reach the transport.
    """

    class Unwritable(ExceptionFilter):
        exception_types = (_HandlerFailed,)

        def catch(self, exc: Exception, context: ExecutionContext) -> object:
            return object()

    @Controller("/broken")
    class BrokenController:
        @UseFilters(Unwritable())
        @Get("/")
        async def read(self) -> dict[str, str]:
            raise _HandlerFailed("the handler failed")

    @Module(controllers=[BrokenController])
    class AppModule:
        pass

    with AsgiTestClient(cast(Any, create_app(AppModule))) as client:
        response = client.get("/broken")

    assert response.status_code == 500
    assert response.headers["content-type"] == "application/problem+json"


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


def test_settings_are_read_back_through_the_server_and_defaults_are_shared() -> None:
    """Hooks and a writer come back from the server exactly as from the application.

    What an application left undeclared comes back as one shared default, the same object
    for every such application, so no request builds one for itself.
    """

    declared = create_app(_notes_module())
    hooks = ObservabilityHooks(metrics=RecordingMetrics())
    set_observability_hooks(declared, hooks)
    set_response_serializer(declared, Envelope("notes"))
    first, second = create_app(_notes_module()), create_app(_notes_module())

    assert observability_hooks_of(declared.get_http_server()) is hooks
    assert response_handler_of(declared.get_http_server()) is response_handler_of(declared)
    assert response_handler_of(declared) is not response_handler_of(first)
    assert response_handler_of(first) is response_handler_of(second.get_http_server())
    assert request_limits_of(first) is request_limits_of(second.get_http_server())


def test_what_an_application_declares_while_serving_governs_its_next_request() -> None:
    """Limits, hooks and a serializer are read for each request, never kept from an earlier one.

    The application serves requests before anything is declared on it, so a setting read
    once and then kept would still be the default for the requests after the declarations.
    """

    metrics = RecordingMetrics()
    application = create_app(_notes_module())

    with AsgiTestClient(cast(Any, application)) as client:
        assert client.get("/notes").json() == {"title": "a note"}
        assert client.post("/notes", json={"title": "ada"}).status_code == 200

        set_request_limits(application, RequestLimits(max_body_bytes=8))
        set_observability_hooks(application, ObservabilityHooks(metrics=metrics))
        set_response_serializer(application, Envelope("notes"))
        served = client.get("/notes")
        refused = client.post("/notes", json={"title": "ada"})

    assert served.json() == {"envelope": "notes", "data": {"title": "a note"}}
    assert refused.status_code == 413
    assert metrics.statuses == ["200", "413"]


def test_two_applications_in_one_process_are_served_under_their_own_settings() -> None:
    """Two applications are objects of the same types, so no setting may be kept by type.

    Requests alternate between the two while both are serving, which is what would show a
    setting one application declared being served to the other.
    """

    first_metrics, second_metrics = RecordingMetrics(), RecordingMetrics()
    first = create_app(
        _notes_module(),
        observability=ObservabilityHooks(metrics=first_metrics),
        response_serializer=Envelope("first"),
    )
    second = create_app(
        _notes_module(),
        observability=ObservabilityHooks(metrics=second_metrics),
        request_limits=RequestLimits(max_body_bytes=8),
        response_serializer=Envelope("second"),
    )

    with (
        AsgiTestClient(cast(Any, first)) as first_client,
        AsgiTestClient(cast(Any, second)) as second_client,
    ):
        for _ in range(2):
            assert first_client.get("/notes").json()["envelope"] == "first"
            assert second_client.get("/notes").json()["envelope"] == "second"
            assert first_client.post("/notes", json={"title": "ada"}).status_code == 200
            assert second_client.post("/notes", json={"title": "ada"}).status_code == 413

    assert first_metrics.statuses == ["200", "200", "200", "200"]
    assert second_metrics.statuses == ["200", "413", "200", "413"]


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


def test_no_request_runs_the_application_protocols_instance_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The application behind a request is found without asking ``ApplicationRuntime``.

    The requests take every path through the runtime - a returned value, a body read under
    the application's limits, a handler that fails and a middleware's refusal - after one
    pass has served each of them once, and none of them may run the protocol's check.
    """

    protocol = type(ApplicationRuntime)
    instancecheck = protocol.__instancecheck__
    checked: list[object] = []

    def counted(cls: type, instance: object) -> bool:
        if cls is ApplicationRuntime:
            checked.append(instance)
        return instancecheck(cls, instance)

    def serve_every_path(client: AsgiTestClient) -> list[int]:
        return [
            client.get("/notes").status_code,
            client.post("/notes", json={"title": "ada"}).status_code,
            client.get("/notes/broken").status_code,
            client.get("/refused").status_code,
        ]

    with AsgiTestClient(cast(Any, create_app(_notes_module()))) as client:
        assert serve_every_path(client) == [200, 200, 500, 400]
        monkeypatch.setattr(protocol, "__instancecheck__", counted)
        assert serve_every_path(client) == [200, 200, 500, 400]

    assert checked == []


def test_a_route_reached_through_the_entry_point_runs_inside_the_bindings_it_made(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The route uses the request and application the entry point bound, not a second binding.

    The handler still finds the request it serves and the application it runs inside, and a
    refusal rendered for a route that never ran is bound only by the entry point as well.
    """

    seen: list[tuple[bool, object]] = []

    @Controller("/notes")
    class NotesController:
        @Get("/")
        async def read(self, request: HttpRequest) -> dict[str, str]:
            bound = application.container.scope_manager
            seen.append((bound.active_request.get() is request, bound.active_application.get()))
            return {"title": "a note"}

    @Controller("/refused")
    class RefusedController:
        @Get("/")
        async def read(self) -> dict[str, str]:
            return {"status": "never reached"}

    @Module(controllers=[NotesController, RefusedController])
    class AppModule:
        def configure(self, consumer: MiddlewareConsumer) -> None:
            consumer.apply(RefuseEveryRequest).for_routes("/refused*")

    application = create_app(AppModule)
    scopes = application.container.scope_manager
    push_request, push_application = scopes.push_request, scopes.push_application
    pushed: list[str] = []

    def counted_push_request(request: HttpRequest | None) -> object:
        pushed.append("request")
        return push_request(request)

    def counted_push_application(running: object) -> object:
        pushed.append("application")
        return push_application(running)

    with AsgiTestClient(cast(Any, application)) as client:
        monkeypatch.setattr(scopes, "push_request", counted_push_request)
        monkeypatch.setattr(scopes, "push_application", counted_push_application)
        served = client.get("/notes").status_code
        served_pushes = pushed.copy()
        pushed.clear()
        refused = client.get("/refused").status_code
        refused_pushes = pushed.copy()

    assert (served, served_pushes) == (200, ["request", "application"])
    assert (refused, refused_pushes) == (400, ["request", "application"])
    [(request_was_bound, running_application)] = seen
    assert request_was_bound
    assert running_application is application


@pytest.mark.anyio
async def test_a_route_run_directly_binds_the_request_and_application_it_is_given(
    build_http_request: HttpRequestFactory,
) -> None:
    """A caller that runs a route itself still has its request and application bound for it.

    So does a request other than the one bound further out: the route binds it for as long
    as it runs and then leaves the outer binding as it found it.
    """

    seen: list[tuple[object, object]] = []

    @Controller("/notes")
    class NotesController:
        @Get("/")
        async def read(self) -> dict[str, str]:
            bound = container.scope_manager
            seen.append((bound.active_request.get(), bound.active_application.get()))
            return {"title": "a note"}

    @Module(controllers=[NotesController])
    class AppModule:
        pass

    graph = build_module_graph(AppModule)
    container = build_container(graph)
    scopes = container.scope_manager
    context = ApplicationContext(container)
    factory = ControllerFactory(container)
    [plan] = compile_execution_plans(compile_route_contracts(graph, container))
    outer = build_http_request(path=plan.path)
    inner = build_http_request(path=plan.path)

    async def run(request: HttpRequest) -> HttpExecutionResult:
        return await execute_http_route(
            application_runtime=context,
            container=container,
            factory=factory,
            execution_plan=plan,
            request=request,
        )

    assert (await run(outer)).error is None
    outer_token = scopes.push_request(outer)
    try:
        assert (await run(inner)).error is None
        assert scopes.active_request.get() is outer
    finally:
        scopes.pop_request(outer_token)

    [(first_request, first_application), (second_request, second_application)] = seen
    assert first_request is outer
    assert second_request is inner
    assert first_application is context
    assert second_application is context
    assert scopes.active_request.get() is None
    assert scopes.active_application.get() is None


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
            ClassProvider(provide=APP_PIPE, use_class=NoopPipe),
            ClassProvider(provide=APP_FILTER, use_class=NeverCatches),
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


def test_a_refusal_carries_the_document_its_status_exception_describes() -> None:
    """The framework writes the router's refusals, so they are the class's own document.

    An application raising ``NotFoundException`` and a router finding no route are one
    condition to the caller, and answering them from the same class is what keeps them
    one shape rather than two that happen to agree today.
    """

    response = not_found_response("/orders/7")

    assert response.status_code == 404
    assert response.media_type == "application/problem+json"
    assert json.loads(response.body) == {
        "type": NotFoundException.problem_type,
        "title": NotFoundException.title,
        "status": 404,
        "detail": NotFoundException.title,
        "instance": "/orders/7",
        "code": NotFoundException.code,
    }


def test_a_wrong_method_names_the_methods_that_would_have_been_answered() -> None:
    response = method_not_allowed_response("/orders", ("GET", "HEAD"))

    assert response.status_code == 405
    assert response.media_type == "application/problem+json"
    assert response.headers["Allow"] == "GET, HEAD"
    assert json.loads(response.body)["code"] == MethodNotAllowedException.code


def test_the_allowed_methods_reach_the_caller_in_one_order_whoever_worked_them_out() -> None:
    """Two transports work the set of methods out separately and iterate it separately.

    Ordering the header here rather than where each transport happens to build it is
    what makes the header a caller reads the same header on every transport.
    """

    from_a_sorted_router = method_not_allowed_response("/orders", ("GET", "HEAD"))
    from_an_unsorted_router = method_not_allowed_response("/orders", ("HEAD", "GET"))

    assert from_a_sorted_router.headers["Allow"] == from_an_unsorted_router.headers["Allow"]
    assert from_an_unsorted_router.headers["Allow"] == "GET, HEAD"


def test_a_refusal_without_a_path_leaves_the_instance_out_rather_than_sending_nothing() -> None:
    assert "instance" not in json.loads(not_found_response().body)
