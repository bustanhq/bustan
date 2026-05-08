"""Integration tests for request observability hooks."""

from __future__ import annotations

from typing import Any, cast

from starlette.testclient import TestClient

from bustan import Controller, Get, Module, create_app
from bustan.logger.observability import ObservabilityHooks


def test_create_app_emits_route_aware_observability_labels() -> None:
    events: list[tuple[object, ...]] = []

    class Span:
        def finish(self, *, status_code: int, error: Exception | None = None) -> None:
            events.append(("finish", status_code, error))

    class Tracer:
        def start_span(self, name: str, *, labels) -> Span:
            events.append(("start", name, dict(labels)))
            return Span()

    class Metrics:
        def record_request(self, *, labels) -> None:
            events.append(("metrics", dict(labels)))

    @Controller("/users", version="1")
    class UsersController:
        @Get("/")
        def read_users(self) -> dict[str, str]:
            return {"status": "ok"}

    @Module(controllers=[UsersController])
    class AppModule:
        pass

    with ObservabilityHooks.scoped_override(ObservabilityHooks(metrics=Metrics(), tracer=Tracer())):
        with TestClient(cast(Any, create_app(AppModule))) as client:
            response = client.get("/users")

    assert response.status_code == 200
    assert events == [
        (
            "start",
            "UsersController.read_users",
            {
                "controller": "UsersController",
                "route": "GET /users",
                "operation": "UsersController.read_users",
                "version": "1",
            },
        ),
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
        ("finish", 200, None),
    ]


def test_create_app_emits_terminal_observability_for_failed_requests() -> None:
    events: list[tuple[object, ...]] = []

    class Span:
        def finish(self, *, status_code: int, error: Exception | None = None) -> None:
            events.append(("finish", status_code, type(error).__name__ if error else None))

    class Tracer:
        def start_span(self, name: str, *, labels) -> Span:
            events.append(("start", name))
            return Span()

    class Metrics:
        def record_request(self, *, labels) -> None:
            events.append(("metrics", dict(labels)))

    @Controller("/fails")
    class FailingController:
        @Get("/")
        def explode(self) -> None:
            raise RuntimeError("boom")

    @Module(controllers=[FailingController])
    class AppModule:
        pass

    with ObservabilityHooks.scoped_override(ObservabilityHooks(metrics=Metrics(), tracer=Tracer())):
        with TestClient(cast(Any, create_app(AppModule))) as client:
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
        ("finish", 500, "RuntimeError"),
    ]