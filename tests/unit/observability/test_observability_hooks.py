"""Unit tests for route-aware observability hooks."""

from __future__ import annotations

from contextlib import contextmanager
from time import perf_counter
from typing import TYPE_CHECKING, Any, cast

from bustan import (
    BadRequestException,
    Controller,
    ExecutionContext,
    Get,
    HttpRequest,
    Middleware,
    MiddlewareConsumer,
    Module,
    create_app,
)
from bustan.observability import observability as observability_module
from bustan.observability.correlation import (
    RequestCorrelation,
    bind_correlation,
    reset_correlation,
)
from bustan.observability.observability import (
    ObservabilityHooks,
    SpanKind,
    SpanStatus,
    build_route_labels,
)
from bustan.testing import AsgiTestClient

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping

    import pytest

    from bustan.observability.observability import SpanContext
    from tests.conftest import RequestFactory


class RecordingSpan:
    """A span that keeps what the runtime did to it, in the order it was done."""

    def __init__(self, events: list[tuple[object, ...]]) -> None:
        self._events = events

    def set_attribute(self, key: str, value: object) -> None:
        self._events.append(("attribute", key, value))

    def set_status(self, status: SpanStatus, *, description: str | None = None) -> None:
        self._events.append(("status", status, description))

    def record_exception(self, error: BaseException) -> None:
        self._events.append(("exception", type(error).__name__))

    def end(self) -> None:
        self._events.append(("end",))


class RecordingTracer:
    """A tracer that keeps every span it was asked to start."""

    def __init__(self) -> None:
        self.events: list[tuple[object, ...]] = []
        self.attributes: list[dict[str, str]] = []
        self.contexts: list[SpanContext] = []

    def start_span(
        self,
        name: str,
        *,
        kind: SpanKind,
        attributes: Mapping[str, str],
        context: SpanContext,
    ) -> RecordingSpan:
        self.events.append(("start", name, kind, dict(attributes)))
        self.attributes.append(dict(attributes))
        self.contexts.append(context)
        return RecordingSpan(self.events)


class RecordingMetrics:
    """A metric sink written against the current contract."""

    def __init__(self) -> None:
        self.records: list[tuple[dict[str, str], float]] = []

    def record_request(self, *, labels: Mapping[str, str], duration_seconds: float) -> None:
        self.records.append((dict(labels), duration_seconds))


def test_labels_include_controller_operation_version_and_status() -> None:
    labels = build_route_labels(_route_contract(), status_code=201)

    assert labels == {
        "controller": "UsersController",
        "route": "GET /users",
        "operation": "UsersController.read_users",
        "version": "1",
        "status": "201",
    }


def test_labels_fall_back_when_the_request_reached_no_route_at_all() -> None:
    assert build_route_labels(None) == {
        "controller": "unknown",
        "route": "unknown",
        "operation": "unknown",
        "version": "neutral",
    }


def test_labels_fall_back_for_unexpected_route_contract_objects() -> None:
    labels = build_route_labels(object(), status_code=503)

    assert labels == {
        "controller": "unknown",
        "route": "unknown",
        "operation": "unknown",
        "version": "neutral",
        "status": "503",
    }


def test_traces_begin_and_end_around_one_canonical_request_execution_path(
    build_request: RequestFactory,
) -> None:
    tracer = RecordingTracer()
    metrics = RecordingMetrics()

    hooks = ObservabilityHooks(metrics=metrics, tracer=tracer)
    observation = hooks.start_request(_execution_context(build_request))
    hooks.finish_request(observation, status_code=200)

    assert tracer.events == [
        (
            "start",
            "UsersController.read_users",
            SpanKind.SERVER,
            {
                "controller": "UsersController",
                "route": "GET /users",
                "operation": "UsersController.read_users",
                "version": "1",
                "correlation_id": tracer.attributes[0]["correlation_id"],
            },
        ),
        ("attribute", "http.status_code", 200),
        ("attribute", "duration_seconds", tracer.events[2][2]),
        ("status", SpanStatus.UNSET, None),
        ("end",),
    ]
    assert [labels for labels, _ in metrics.records] == [
        {
            "controller": "UsersController",
            "route": "GET /users",
            "operation": "UsersController.read_users",
            "version": "1",
            "status": "200",
        }
    ]


def test_duration_measured_by_the_runtime_reaches_the_metric_sink(
    build_request: RequestFactory,
) -> None:
    metrics = RecordingMetrics()
    hooks = ObservabilityHooks(metrics=metrics)

    observation = hooks.start_request(_execution_context(build_request))
    _busy_for(0.01)
    hooks.finish_request(observation, status_code=200)

    assert len(metrics.records) == 1
    _, duration_seconds = metrics.records[0]
    # The lower bound is what the handler actually spent, so a duration that is a
    # placeholder rather than a measurement fails here. The upper bound is generous
    # on purpose: it catches a duration read off the wrong clock without turning a
    # loaded machine into a test failure.
    assert 0.01 <= duration_seconds < 30.0


def test_duration_also_reaches_a_sink_written_before_the_duration_existed(
    build_request: RequestFactory,
) -> None:
    class LegacyMetrics:
        def __init__(self) -> None:
            self.records: list[dict[str, str]] = []

        def record_request(self, *, labels: Mapping[str, str]) -> None:
            self.records.append(dict(labels))

    metrics = LegacyMetrics()
    hooks = ObservabilityHooks(metrics=cast(Any, metrics))

    observation = hooks.start_request(_execution_context(build_request))
    hooks.finish_request(observation, status_code=200)

    assert [record["status"] for record in metrics.records] == ["200"]


def test_failed_requests_still_emit_terminal_metrics_and_trace_state(
    build_request: RequestFactory,
) -> None:
    tracer = RecordingTracer()
    metrics = RecordingMetrics()

    hooks = ObservabilityHooks(metrics=metrics, tracer=tracer)
    observation = hooks.start_request(_execution_context(build_request))
    hooks.finish_request(observation, status_code=500, error=RuntimeError("boom"))

    assert tracer.events[1:] == [
        ("attribute", "http.status_code", 500),
        ("attribute", "duration_seconds", tracer.events[2][2]),
        ("exception", "RuntimeError"),
        ("status", SpanStatus.ERROR, "RuntimeError: boom"),
        ("end",),
    ]
    assert [labels["status"] for labels, _ in metrics.records] == ["500"]


def test_a_server_error_without_an_exception_still_ends_the_span_in_error(
    build_request: RequestFactory,
) -> None:
    tracer = RecordingTracer()

    hooks = ObservabilityHooks(tracer=tracer)
    observation = hooks.start_request(_execution_context(build_request))
    hooks.finish_request(observation, status_code=503)

    assert ("status", SpanStatus.ERROR, "status 503") in tracer.events


def test_the_span_joins_the_trace_the_caller_sent_and_names_the_callers_span(
    build_request: RequestFactory,
) -> None:
    tracer = RecordingTracer()
    correlation = RequestCorrelation(
        correlation_id="from-the-caller",
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
        span_id="00f067aa0ba902b7",
        parent_span_id="a1a2a3a4b1b2b3b4",
        parent_sampled=True,
    )

    with _bound(correlation):
        hooks = ObservabilityHooks(tracer=tracer)
        hooks.start_request(_execution_context(build_request))

    assert tracer.contexts[0].trace_id == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert tracer.contexts[0].span_id == "00f067aa0ba902b7"
    assert tracer.contexts[0].parent_span_id == "a1a2a3a4b1b2b3b4"
    assert tracer.contexts[0].sampled is True
    assert tracer.attributes[0]["correlation_id"] == "from-the-caller"


def test_head_sampling_drops_the_span_but_keeps_the_metric(
    build_request: RequestFactory,
) -> None:
    tracer = RecordingTracer()
    metrics = RecordingMetrics()

    hooks = ObservabilityHooks(metrics=metrics, tracer=tracer, sample_ratio=0.0)
    observation = hooks.start_request(_execution_context(build_request))
    hooks.finish_request(observation, status_code=200)

    assert tracer.events == []
    assert observation.span_context is not None
    assert observation.span_context.sampled is False
    assert len(metrics.records) == 1


def test_head_sampling_honours_a_sampled_caller_whatever_the_local_ratio_is(
    build_request: RequestFactory,
) -> None:
    tracer = RecordingTracer()
    correlation = RequestCorrelation(
        correlation_id="from-the-caller",
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
        span_id="00f067aa0ba902b7",
        parent_span_id="a1a2a3a4b1b2b3b4",
        parent_sampled=True,
    )

    with _bound(correlation):
        hooks = ObservabilityHooks(tracer=tracer, sample_ratio=0.0)
        hooks.start_request(_execution_context(build_request))

    assert [event[0] for event in tracer.events] == ["start"]


def test_scoped_override_restores_previous_hooks() -> None:
    outer = ObservabilityHooks()
    inner = ObservabilityHooks()

    with ObservabilityHooks.scoped_override(outer):
        assert ObservabilityHooks.current() is outer
        with ObservabilityHooks.scoped_override(inner):
            assert ObservabilityHooks.current() is inner
        assert ObservabilityHooks.current() is outer

    assert ObservabilityHooks.current() is not outer
    assert ObservabilityHooks.current() is not inner


def test_global_override_reset_restores_previous_hooks_in_stack_order() -> None:
    outer = ObservabilityHooks()
    inner = ObservabilityHooks()

    ObservabilityHooks.reset_global()
    ObservabilityHooks.override_global(outer)
    ObservabilityHooks.override_global(inner)
    try:
        assert ObservabilityHooks.current() is inner
        ObservabilityHooks.reset_global()
        assert ObservabilityHooks.current() is outer
    finally:
        ObservabilityHooks.reset_global()

    assert ObservabilityHooks.current() is not outer
    assert ObservabilityHooks.current() is not inner


@contextmanager
def _bound(correlation: RequestCorrelation) -> Iterator[None]:
    """Serve the block as though a request arrived carrying *correlation*."""

    token = bind_correlation(correlation)
    try:
        yield
    finally:
        reset_correlation(token)


def _busy_for(seconds: float) -> None:
    """Spend *seconds* on the same clock the runtime measures durations with."""

    deadline = perf_counter() + seconds
    while perf_counter() < deadline:
        pass


def _execution_context(build_request: RequestFactory) -> ExecutionContext:
    request = build_request(path="/users")

    class UsersController:
        def read_users(self) -> None:
            return None

    controller = UsersController()
    return ExecutionContext.create_http(
        request=request,
        response=None,
        handler=controller.read_users,
        controller_cls=UsersController,
        module=cast(Any, UsersController),
        controller=controller,
        container=cast(Any, object()),
        route_contract=_route_contract(),
    )


def _route_contract() -> object:
    class UsersController:
        pass

    return type(
        "RouteContractStub",
        (),
        {
            "controller_cls": UsersController,
            "method": "GET",
            "path": "/users",
            "handler_name": "read_users",
            "versions": ("1",),
        },
    )()


def test_a_sink_taking_open_keywords_is_given_the_duration(
    build_request: RequestFactory,
) -> None:
    class OpenMetrics:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def record_request(self, **fields: object) -> None:
            self.calls.append(fields)

    metrics = OpenMetrics()
    hooks = ObservabilityHooks(metrics=cast(Any, metrics))

    observation = hooks.start_request(_execution_context(build_request))
    hooks.finish_request(observation, status_code=200)

    assert "duration_seconds" in metrics.calls[0]


def test_a_sink_whose_signature_cannot_be_read_is_taken_at_the_current_contract(
    build_request: RequestFactory,
) -> None:
    """An unreadable signature is not evidence that a sink predates the duration.

    Some callables cannot be introspected at all, and downgrading every one of them
    would quietly deny the duration to sinks that do accept it.
    """

    class OpaqueMetrics:
        def __init__(self) -> None:
            self.calls: list[float] = []

        def record_request(self, *, labels: Mapping[str, str], duration_seconds: float) -> None:
            self.calls.append(duration_seconds)

    metrics = OpaqueMetrics()
    # A signature that cannot be parsed is what an accelerated or wrapped sink looks
    # like from here, and it is the only way to produce one deterministically.
    cast(Any, OpaqueMetrics.record_request).__signature__ = "not a signature"
    hooks = ObservabilityHooks(metrics=cast(Any, metrics))

    observation = hooks.start_request(_execution_context(build_request))
    hooks.finish_request(observation, status_code=200)

    assert len(metrics.calls) == 1


def test_an_application_with_no_sinks_builds_no_labels_span_context_or_clock_reading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nothing listens to such an application, so nothing a listener reads is built.

    Both ways of having no sinks are served: declaring no hooks, and declaring hooks
    built without a sink or a tracer. The refused route is answered on the path that
    renders an exception for a route that never ran, which hands whatever
    ``start_request`` returned to ``finish_request`` without looking at it.
    """

    made = _count_observation_work(monkeypatch)
    applications = (
        create_app(_served_module()),
        create_app(_served_module(), observability=ObservabilityHooks()),
    )

    statuses: list[int] = []
    for application in applications:
        with AsgiTestClient(cast(Any, application)) as client:
            statuses.extend(client.get(path).status_code for path in _SERVED_PATHS)

    assert statuses == [200, 200, 400, 200, 200, 400]
    assert made == []


def test_a_route_is_labelled_once_however_many_requests_it_serves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A route's labels follow from its contract, so its first request builds them.

    The span contexts are the control: each belongs to one request, so one is still
    built for every request, which shows the count sees the work the hooks do.
    """

    made = _count_observation_work(monkeypatch)
    metrics = RecordingMetrics()
    tracer = RecordingTracer()
    application = create_app(
        _served_module(), observability=ObservabilityHooks(metrics=metrics, tracer=tracer)
    )

    with AsgiTestClient(cast(Any, application)) as client:
        for path in ("/users", "/orders", "/users", "/refused", "/orders"):
            client.get(path)

    users = {
        "controller": "UsersController",
        "route": "GET /users",
        "operation": "UsersController.read_users",
        "version": "1",
    }
    orders = {
        "controller": "OrdersController",
        "route": "GET /orders",
        "operation": "OrdersController.read_orders",
        "version": "neutral",
    }
    refused = {
        "controller": "RefusedController",
        "route": "GET /refused",
        "operation": "RefusedController.read_refused",
        "version": "neutral",
    }
    assert [labels for labels, _ in metrics.records] == [
        {**users, "status": "200"},
        {**orders, "status": "200"},
        {**users, "status": "200"},
        {**refused, "status": "400"},
        {**orders, "status": "200"},
    ]
    assert [
        {key: value for key, value in attributes.items() if key != "correlation_id"}
        for attributes in tracer.attributes
    ] == [users, orders, users, refused, orders]
    assert made.count("labels") == 3
    assert made.count("span context") == 5


def test_a_sink_or_tracer_that_rewrites_what_it_was_given_cannot_relabel_a_later_request(
    build_request: RequestFactory,
) -> None:
    """Every request of a route shares its labels; what a listener is handed is its own."""

    class RewritingMetrics(RecordingMetrics):
        def record_request(self, *, labels: Mapping[str, str], duration_seconds: float) -> None:
            super().record_request(labels=labels, duration_seconds=duration_seconds)
            cast(dict[str, str], labels)["operation"] = "rewritten"

    class RewritingTracer(RecordingTracer):
        def start_span(
            self,
            name: str,
            *,
            kind: SpanKind,
            attributes: Mapping[str, str],
            context: SpanContext,
        ) -> RecordingSpan:
            span = super().start_span(name, kind=kind, attributes=attributes, context=context)
            cast(dict[str, str], attributes)["operation"] = "rewritten"
            return span

    metrics = RewritingMetrics()
    tracer = RewritingTracer()
    hooks = ObservabilityHooks(metrics=metrics, tracer=tracer)
    context = _execution_context(build_request)

    for _ in range(2):
        hooks.finish_request(hooks.start_request(context), status_code=200)

    operation = "UsersController.read_users"
    assert [labels["operation"] for labels, _ in metrics.records] == [operation, operation]
    assert [attributes["operation"] for attributes in tracer.attributes] == [operation, operation]


def test_every_application_that_declared_no_hooks_is_served_by_one_hooks_object() -> None:
    configured = ObservabilityHooks()
    override = ObservabilityHooks()
    shared = ObservabilityHooks.resolve(None)

    assert ObservabilityHooks.resolve(None) is shared
    assert ObservabilityHooks.resolve(configured) is configured
    with ObservabilityHooks.scoped_override(override):
        assert ObservabilityHooks.resolve(None) is override
        assert ObservabilityHooks.resolve(configured) is override
    assert ObservabilityHooks.resolve(None) is shared


def test_a_scoped_or_global_override_observes_the_requests_it_covers_and_no_others() -> None:
    scoped_metrics = RecordingMetrics()
    global_metrics = RecordingMetrics()
    configured_metrics = RecordingMetrics()
    unconfigured = create_app(_served_module())
    configured = create_app(
        _served_module(), observability=ObservabilityHooks(metrics=configured_metrics)
    )

    with (
        AsgiTestClient(cast(Any, unconfigured)) as unconfigured_client,
        AsgiTestClient(cast(Any, configured)) as configured_client,
    ):
        with ObservabilityHooks.scoped_override(ObservabilityHooks(metrics=scoped_metrics)):
            unconfigured_client.get("/users")
            configured_client.get("/users")
        ObservabilityHooks.override_global(ObservabilityHooks(metrics=global_metrics))
        try:
            unconfigured_client.get("/orders")
            configured_client.get("/orders")
        finally:
            ObservabilityHooks.reset_global()
        unconfigured_client.get("/refused")
        configured_client.get("/refused")

    assert [labels["operation"] for labels, _ in scoped_metrics.records] == [
        "UsersController.read_users",
        "UsersController.read_users",
    ]
    assert [labels["operation"] for labels, _ in global_metrics.records] == [
        "OrdersController.read_orders",
        "OrdersController.read_orders",
    ]
    assert [labels["operation"] for labels, _ in configured_metrics.records] == [
        "RefusedController.read_refused"
    ]


_SERVED_PATHS = ("/users", "/orders", "/refused")


def _served_module() -> type[object]:
    """Return a module serving two routes, and a third a middleware refuses before it runs."""

    @Controller("/users", version="1")
    class UsersController:
        @Get("/")
        async def read_users(self) -> dict[str, str]:
            return {"status": "ok"}

    @Controller("/orders")
    class OrdersController:
        @Get("/")
        async def read_orders(self) -> dict[str, str]:
            return {"status": "ok"}

    @Controller("/refused")
    class RefusedController:
        @Get("/")
        async def read_refused(self) -> dict[str, str]:
            return {"status": "never reached"}

    class RefusingMiddleware(Middleware):
        async def use(self, request: HttpRequest, call_next: Any) -> Any:
            raise BadRequestException("the middleware refused the request")

    @Module(controllers=[UsersController, OrdersController, RefusedController])
    class AppModule:
        def configure(self, consumer: MiddlewareConsumer) -> None:
            consumer.apply(RefusingMiddleware).for_routes("/refused*")

    return AppModule


def _count_observation_work(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Name, in order, each label set, span context and clock reading the hooks make."""

    made: list[str] = []

    def counted(name: str, original: Callable[..., Any]) -> Callable[..., Any]:
        def record(*args: Any, **kwargs: Any) -> Any:
            made.append(name)
            return original(*args, **kwargs)

        return record

    for name, attribute in (
        ("labels", "build_route_labels"),
        ("span context", "SpanContext"),
        ("clock reading", "perf_counter"),
    ):
        original = getattr(observability_module, attribute)
        monkeypatch.setattr(observability_module, attribute, counted(name, original))
    return made
