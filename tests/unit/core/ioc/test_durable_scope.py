"""Unit tests for durable provider scope resolution."""

from __future__ import annotations

from typing import Any, cast

from starlette.requests import Request

from bustan import Injectable, Module, Scope
from bustan.core.ioc.container import build_container
from bustan.core.module.graph import build_module_graph


def test_durable_scope_reuses_instances_for_the_same_context_key() -> None:
    @Injectable(scope=Scope.DURABLE)
    class DurableService:
        @classmethod
        def get_durable_context_key(cls, request: Request | None) -> str:
            assert request is not None
            return request.headers["x-tenant-id"]

    @Module(providers=[DurableService], exports=[DurableService])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    request = _build_request("/items", headers=[(b"x-tenant-id", b"tenant-a")])

    first = cast(Any, container.resolve(DurableService, module=AppModule, request=request))
    second = cast(Any, container.resolve(DurableService, module=AppModule, request=request))

    assert first is second


def test_durable_scope_isolated_by_context_key() -> None:
    @Injectable(scope=Scope.DURABLE)
    class DurableService:
        @classmethod
        def get_durable_context_key(cls, request: Request | None) -> str:
            assert request is not None
            return request.headers["x-tenant-id"]

    @Module(providers=[DurableService], exports=[DurableService])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    first_request = _build_request("/items", headers=[(b"x-tenant-id", b"tenant-a")])
    second_request = _build_request("/items", headers=[(b"x-tenant-id", b"tenant-b")])

    first = cast(Any, container.resolve(DurableService, module=AppModule, request=first_request))
    second = cast(
        Any, container.resolve(DurableService, module=AppModule, request=second_request)
    )

    assert first is not second


def _build_request(path: str, *, headers: list[tuple[bytes, bytes]]) -> Request:
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": b"",
        "headers": [(b"host", b"testserver"), *headers],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
        "path_params": {},
    }

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(scope, receive)
