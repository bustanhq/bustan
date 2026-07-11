"""Integration tests for canonical route middleware attachment."""

from __future__ import annotations

from typing import Any, cast

from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from bustan import Controller, ExceptionFilter, Get, Middleware, Module, UseFilters, create_app
from bustan.platform.http.abstractions import HttpRequest
from bustan.pipeline.middleware import MiddlewareConsumer


class RootOrderMiddleware(Middleware):
    async def use(self, request, call_next):
        request.state.events = [*getattr(request.state, "events", []), "root"]
        return await call_next(request)


class UsersOrderMiddleware(Middleware):
    async def use(self, request, call_next):
        request.state.events = [*getattr(request.state, "events", []), "users"]
        return await call_next(request)


class BoomMiddleware(Middleware):
    async def use(self, request, call_next):
        raise RuntimeError("middleware boom")


class RuntimeErrorFilter(ExceptionFilter):
    exception_types = (RuntimeError,)

    async def catch(self, exc: Exception, context) -> object:
        return JSONResponse({"detail": str(exc)}, status_code=418)


def test_create_app_runs_route_middleware_in_module_order() -> None:
    @Controller("/users")
    class UsersController:
        @Get("/")
        def read_users(self, request: HttpRequest) -> dict[str, list[str]]:
            return {"events": list(request.state.events)}

    @Module(controllers=[UsersController])
    class UsersModule:
        def configure(self, consumer: MiddlewareConsumer) -> None:
            consumer.apply(UsersOrderMiddleware).for_routes(UsersController)

    @Module(imports=[UsersModule])
    class AppModule:
        def configure(self, consumer: MiddlewareConsumer) -> None:
            consumer.apply(RootOrderMiddleware).for_routes(UsersController)

    application = create_app(AppModule)

    with TestClient(cast(Any, application)) as client:
        response = client.get("/users")

    assert response.status_code == 200
    assert response.json() == {"events": ["root", "users"]}


def test_create_app_routes_middleware_exceptions_through_filters() -> None:
    @Controller("/users")
    class UsersController:
        @UseFilters(RuntimeErrorFilter())
        @Get("/")
        def read_users(self) -> dict[str, str]:
            return {"status": "ok"}

    @Module(controllers=[UsersController])
    class AppModule:
        def configure(self, consumer: MiddlewareConsumer) -> None:
            consumer.apply(BoomMiddleware).for_routes(UsersController)

    application = create_app(AppModule)

    with TestClient(cast(Any, application)) as client:
        response = client.get("/users")

    assert response.status_code == 418
    assert response.json() == {"detail": "middleware boom"}