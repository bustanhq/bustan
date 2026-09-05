"""A request that fails in a middleware is answered like one that fails in a handler."""

from __future__ import annotations

from typing import Any, cast

from starlette.testclient import TestClient

from bustan import Controller, Get, Middleware, Module, create_app
from bustan.contracts import HttpRequest
from bustan.core.errors import BadRequestException
from bustan.pipeline.middleware import MiddlewareConsumer


class FailingMiddleware(Middleware):
    async def use(self, request: HttpRequest, call_next):
        raise BadRequestException("middleware refused the request")


def _client(module: type[object], *, debug: bool = False) -> TestClient:
    return TestClient(cast(Any, create_app(module, debug=debug)))


def test_the_middleware_failure_path_answers_in_the_same_content_type() -> None:
    @Controller("/handler")
    class HandlerController:
        @Get("/")
        def index(self) -> dict[str, str]:
            raise BadRequestException("the handler refused the request")

    @Controller("/middleware")
    class MiddlewareController:
        @Get("/")
        def index(self) -> dict[str, str]:
            return {"status": "never reached"}

    @Module(controllers=[HandlerController, MiddlewareController])
    class AppModule:
        def configure(self, consumer: MiddlewareConsumer) -> None:
            consumer.apply(FailingMiddleware).for_routes("/middleware*")

    with _client(AppModule) as client:
        from_handler = client.get("/handler")
        from_middleware = client.get("/middleware")

    assert from_handler.status_code == 400
    assert from_middleware.status_code == 400
    assert from_middleware.headers["content-type"] == from_handler.headers["content-type"]
    assert from_middleware.json()["title"] == from_handler.json()["title"]


def test_a_resolution_failure_on_the_middleware_path_leaks_nothing_under_debug() -> None:
    @Controller("/middleware")
    class BrokenController:
        def __init__(self) -> None:
            raise RuntimeError("controller construction blew up")

        @Get("/")
        def index(self) -> dict[str, str]:
            return {"status": "never reached"}

    @Module(controllers=[BrokenController])
    class AppModule:
        def configure(self, consumer: MiddlewareConsumer) -> None:
            consumer.apply(FailingMiddleware).for_routes("/middleware*")

    with _client(AppModule, debug=True) as client:
        response = client.get("/middleware")

    body = response.text

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"detail": "Internal server error"}
    assert "Traceback" not in body
    assert "controller construction blew up" not in body
