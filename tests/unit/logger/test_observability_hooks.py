"""Unit tests for route-aware observability hooks."""

from __future__ import annotations

from typing import Any, cast

from starlette.requests import Request

from bustan import ExecutionContext
from bustan.logger.observability import ObservabilityHooks, build_route_labels


def test_labels_include_controller_operation_version_and_status() -> None:
    labels = build_route_labels(_route_contract(), status_code=201)

    assert labels == {
        "controller": "UsersController",
        "route": "GET /users",
        "operation": "UsersController.read_users",
        "version": "1",
        "status": "201",
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


def test_traces_begin_and_end_around_one_canonical_request_execution_path() -> None:
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

    hooks = ObservabilityHooks(metrics=Metrics(), tracer=Tracer())
    observation = hooks.start_request(_execution_context())
    events.append(("handler",))
    hooks.finish_request(observation, status_code=200)

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
        ("handler",),
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


def test_failed_requests_still_emit_terminal_metrics_and_trace_state() -> None:
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

    hooks = ObservabilityHooks(metrics=Metrics(), tracer=Tracer())
    observation = hooks.start_request(_execution_context())
    hooks.finish_request(observation, status_code=500, error=RuntimeError("boom"))

    assert events == [
        ("start", "UsersController.read_users"),
        (
            "metrics",
            {
                "controller": "UsersController",
                "route": "GET /users",
                "operation": "UsersController.read_users",
                "version": "1",
                "status": "500",
            },
        ),
        ("finish", 500, "RuntimeError"),
    ]


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


def _execution_context() -> ExecutionContext:
    request = _build_request("/users")

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


def _build_request(path: str) -> Request:
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": b"",
        "headers": [(b"host", b"testserver")],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
        "path_params": {},
    }

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(scope, receive)