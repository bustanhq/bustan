"""Unit tests for route-aware observability hooks."""

from __future__ import annotations

from contextlib import contextmanager
from time import perf_counter
from typing import TYPE_CHECKING, Any, cast

from bustan import ExecutionContext
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

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

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
