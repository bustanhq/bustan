"""Unit tests for the throttler module."""

from __future__ import annotations

from typing import Any, cast

from starlette.testclient import TestClient

from bustan import Controller, Get, Module, SkipThrottle, ThrottlerModule, create_app


def test_throttler_module_rejects_requests_above_the_limit() -> None:
    @Controller("/")
    class AppController:
        @Get("/")
        def index(self) -> dict[str, str]:
            return {"status": "ok"}

    @Module(imports=[ThrottlerModule.for_root(ttl=60, limit=1)], controllers=[AppController])
    class AppModule:
        pass

    with TestClient(cast(Any, create_app(AppModule))) as client:
        first = client.get("/")
        second = client.get("/")

    assert first.status_code == 200
    assert first.headers["X-RateLimit-Limit"] == "1"
    assert second.status_code == 429


def test_skip_throttle_decorator_bypasses_the_guard() -> None:
    @Controller("/")
    class AppController:
        @SkipThrottle
        @Get("/")
        def index(self) -> dict[str, str]:
            return {"status": "ok"}

    @Module(imports=[ThrottlerModule.for_root(ttl=60, limit=1)], controllers=[AppController])
    class AppModule:
        pass

    with TestClient(cast(Any, create_app(AppModule))) as client:
        assert client.get("/").status_code == 200
        assert client.get("/").status_code == 200


def test_throttler_module_supports_custom_key_resolution() -> None:
    @Controller("/")
    class AppController:
        @Get("/")
        def index(self) -> dict[str, str]:
            return {"status": "ok"}

    @Module(
        imports=[
            ThrottlerModule.for_root(
                ttl=60,
                limit=1,
                key_resolver=lambda context: f"client:{context.request.headers.get('x-client-id', 'missing')}",
            )
        ],
        controllers=[AppController],
    )
    class AppModule:
        pass

    with TestClient(cast(Any, create_app(AppModule))) as client:
        first = client.get("/", headers={"x-client-id": "a"})
        second = client.get("/", headers={"x-client-id": "b"})
        third = client.get("/", headers={"x-client-id": "a"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429
