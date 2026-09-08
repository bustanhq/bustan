"""Integration tests for request observability hooks."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, cast

from bustan import Controller, Get, Logger, Module, create_app
from bustan.observability.logger import FRAMEWORK_LOGGER_NAME
from bustan.observability.observability import ObservabilityHooks, SpanKind, SpanStatus
from bustan.testing import AsgiTestClient

if TYPE_CHECKING:
    from collections.abc import Mapping

    import pytest

    from bustan.observability.observability import SpanContext

_CALLER_TRACEPARENT = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"


class Span:
    """A span that keeps what the runtime did to it."""

    def __init__(self, events: list[tuple[object, ...]]) -> None:
        self._events = events

    def set_attribute(self, key: str, value: object) -> None:
        self._events.append(("attribute", key, value))

    def set_status(self, status: SpanStatus, *, description: str | None = None) -> None:
        self._events.append(("status", status))

    def record_exception(self, error: BaseException) -> None:
        self._events.append(("exception", type(error).__name__))

    def end(self) -> None:
        self._events.append(("end",))


class Tracer:
    """A tracer that keeps every span it started, with the context it started it in."""

    def __init__(self, events: list[tuple[object, ...]]) -> None:
        self._events = events
        self.attributes: list[dict[str, str]] = []
        self.contexts: list[SpanContext] = []

    def start_span(
        self,
        name: str,
        *,
        kind: SpanKind,
        attributes: Mapping[str, str],
        context: SpanContext,
    ) -> Span:
        self._events.append(("start", name))
        self.attributes.append(dict(attributes))
        self.contexts.append(context)
        return Span(self._events)


class Metrics:
    """A metric sink keeping the labels and the duration of every finished request."""

    def __init__(self, events: list[tuple[object, ...]]) -> None:
        self._events = events
        self.durations: list[float] = []

    def record_request(self, *, labels: Mapping[str, str], duration_seconds: float) -> None:
        self._events.append(("metrics", dict(labels)))
        self.durations.append(duration_seconds)


def test_create_app_emits_route_aware_observability_labels() -> None:
    events: list[tuple[object, ...]] = []

    @Controller("/users", version="1")
    class UsersController:
        @Get("/")
        def read_users(self) -> dict[str, str]:
            return {"status": "ok"}

    @Module(controllers=[UsersController])
    class AppModule:
        pass

    metrics = Metrics(events)
    with (
        ObservabilityHooks.scoped_override(
            ObservabilityHooks(metrics=metrics, tracer=Tracer(events))
        ),
        AsgiTestClient(cast(Any, create_app(AppModule))) as client,
    ):
        response = client.get("/users")

    assert response.status_code == 200
    assert events == [
        ("start", "UsersController.read_users"),
        (
            "metrics",
            {
                "controller": "UsersController",
                "route": "GET /users",
                "operation": "UsersController.read_users",
                "version": "1",
                "status": "200",
            },
        ),
        ("attribute", "http.status_code", 200),
        ("attribute", "duration_seconds", events[3][2]),
        ("status", SpanStatus.UNSET),
        ("end",),
    ]
    # The measurement is the request's own, so it is positive and it is not a whole
    # second: a placeholder would be neither.
    assert 0.0 < metrics.durations[0] < 30.0


def test_create_app_emits_terminal_observability_for_failed_requests() -> None:
    events: list[tuple[object, ...]] = []

    @Controller("/fails")
    class FailingController:
        @Get("/")
        def explode(self) -> None:
            raise RuntimeError("boom")

    @Module(controllers=[FailingController])
    class AppModule:
        pass

    with (
        ObservabilityHooks.scoped_override(
            ObservabilityHooks(metrics=Metrics(events), tracer=Tracer(events))
        ),
        AsgiTestClient(cast(Any, create_app(AppModule))) as client,
    ):
        response = client.get("/fails")

    assert response.status_code == 500
    assert events == [
        ("start", "FailingController.explode"),
        (
            "metrics",
            {
                "controller": "FailingController",
                "route": "GET /fails",
                "operation": "FailingController.explode",
                "version": "neutral",
                "status": "500",
            },
        ),
        ("attribute", "http.status_code", 500),
        ("attribute", "duration_seconds", events[3][2]),
        ("exception", "RuntimeError"),
        ("status", SpanStatus.ERROR),
        ("end",),
    ]


def test_one_correlation_id_reaches_both_the_log_record_and_the_span(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The id the caller sent names the request everywhere it is written down."""

    caplog.set_level(logging.DEBUG, logger=FRAMEWORK_LOGGER_NAME)
    events: list[tuple[object, ...]] = []

    @Controller("/orders")
    class OrdersController:
        @Get("/")
        def read_orders(self) -> dict[str, str]:
            Logger("Orders").log("serving orders")
            return {"status": "ok"}

    @Module(controllers=[OrdersController])
    class AppModule:
        pass

    tracer = Tracer(events)
    Logger.reset_logger()
    with (
        ObservabilityHooks.scoped_override(ObservabilityHooks(tracer=tracer)),
        AsgiTestClient(cast(Any, create_app(AppModule))) as client,
    ):
        response = client.get("/orders", headers={"x-correlation-id": "req-42"})

    assert response.status_code == 200
    logged = [
        json.loads(record.getMessage())
        for record in caplog.records
        if record.name == FRAMEWORK_LOGGER_NAME
    ]
    assert [record["correlation_id"] for record in logged] == ["req-42"]
    assert tracer.attributes[0]["correlation_id"] == "req-42"
    assert logged[0]["trace_id"] == tracer.contexts[0].trace_id
    assert logged[0]["span_id"] == tracer.contexts[0].span_id


def test_a_request_that_arrives_in_a_trace_continues_it() -> None:
    events: list[tuple[object, ...]] = []

    @Controller("/orders")
    class OrdersController:
        @Get("/")
        def read_orders(self) -> dict[str, str]:
            return {"status": "ok"}

    @Module(controllers=[OrdersController])
    class AppModule:
        pass

    tracer = Tracer(events)
    with (
        ObservabilityHooks.scoped_override(ObservabilityHooks(tracer=tracer)),
        AsgiTestClient(cast(Any, create_app(AppModule))) as client,
    ):
        client.get("/orders", headers={"traceparent": _CALLER_TRACEPARENT})

    assert tracer.contexts[0].trace_id == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert tracer.contexts[0].parent_span_id == "00f067aa0ba902b7"
    assert tracer.contexts[0].sampled is True


def test_two_requests_are_two_correlations() -> None:
    events: list[tuple[object, ...]] = []

    @Controller("/orders")
    class OrdersController:
        @Get("/")
        def read_orders(self) -> dict[str, str]:
            return {"status": "ok"}

    @Module(controllers=[OrdersController])
    class AppModule:
        pass

    tracer = Tracer(events)
    with (
        ObservabilityHooks.scoped_override(ObservabilityHooks(tracer=tracer)),
        AsgiTestClient(cast(Any, create_app(AppModule))) as client,
    ):
        client.get("/orders")
        client.get("/orders")

    first, second = tracer.attributes
    assert first["correlation_id"] != second["correlation_id"]
    assert tracer.contexts[0].trace_id != tracer.contexts[1].trace_id
