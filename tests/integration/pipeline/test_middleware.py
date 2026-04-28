"""Integration tests for module-configured middleware."""

from __future__ import annotations

from typing import Any, cast

from starlette.testclient import TestClient

from bustan import Controller, Get, Middleware, Module, create_app
from bustan.pipeline.middleware import MiddlewareConsumer


class HeaderMiddleware(Middleware):
    async def use(self, request, call_next):
        response = await call_next(request)
        response.headers["x-middleware-hit"] = "yes"
        return response


def test_module_configure_registers_middleware_for_matching_routes() -> None:
    @Controller("/users")
    class UsersController:
        @Get("/")
        def index(self) -> dict[str, str]:
            return {"status": "ok"}

    @Controller("/health")
    class HealthController:
        @Get("/")
        def index(self) -> dict[str, str]:
            return {"status": "up"}

    @Module(controllers=[UsersController, HealthController])
    class AppModule:
        def configure(self, consumer: MiddlewareConsumer) -> None:
            consumer.apply(HeaderMiddleware).for_routes("/users*").exclude("/health*")

    application = create_app(AppModule)

    with TestClient(cast(Any, application)) as client:
        users_response = client.get("/users")
        health_response = client.get("/health")

    assert users_response.headers["x-middleware-hit"] == "yes"
    assert "x-middleware-hit" not in health_response.headers
