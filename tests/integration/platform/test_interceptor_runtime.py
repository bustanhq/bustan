"""Integration tests for interceptor runtime behavior."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, cast

from starlette.testclient import TestClient

from bustan import APP_INTERCEPTOR, Controller, ExecutionContext, Get, Interceptor, Module, UseInterceptors, create_app
from bustan.pipeline.interceptors import CallHandler


def test_create_app_executes_interceptors_in_canonical_attachment_order() -> None:
    events: list[str] = []

    class GlobalInterceptor(Interceptor):
        async def intercept(self, context: ExecutionContext, next: CallHandler) -> object:
            events.append("global:before")
            result = await next.handle()
            events.append("global:after")
            return {"global": result}

    class ControllerInterceptor(Interceptor):
        async def intercept(self, context: ExecutionContext, next: CallHandler) -> object:
            events.append("controller:before")
            result = await next.handle()
            events.append("controller:after")
            return {"controller": result}

    class HandlerInterceptor(Interceptor):
        async def intercept(self, context: ExecutionContext, next: CallHandler) -> object:
            events.append("handler:before")
            result = await next.handle()
            events.append("handler:after")
            return {"handler": result}

    @UseInterceptors(ControllerInterceptor())
    @Controller("/users")
    class UsersController:
        @UseInterceptors(HandlerInterceptor())
        @Get("/")
        def read_users(self) -> dict[str, str]:
            events.append("handler")
            return {"status": "ok"}

    @Module(
        controllers=[UsersController],
        providers=[{"provide": APP_INTERCEPTOR, "use_value": GlobalInterceptor()}],
    )
    class AppModule:
        pass

    with TestClient(cast(Any, create_app(AppModule))) as client:
        response = client.get("/users")

    assert response.status_code == 200
    assert response.json() == {
        "global": {"controller": {"handler": {"status": "ok"}}}
    }
    assert events == [
        "global:before",
        "controller:before",
        "handler:before",
        "handler",
        "handler:after",
        "controller:after",
        "global:after",
    ]


def test_create_app_supports_stream_transforming_interceptors() -> None:
    class UppercaseStreamInterceptor(Interceptor):
        async def intercept(self, context: ExecutionContext, next: CallHandler) -> object:
            stream = await next.handle()

            async def wrapped() -> AsyncIterator[bytes]:
                async for chunk in cast(AsyncIterator[bytes], stream):
                    yield chunk.upper()

            return wrapped()

    @Controller("/streams")
    class StreamController:
        @UseInterceptors(UppercaseStreamInterceptor())
        @Get("/")
        async def read_stream(self) -> AsyncIterator[bytes]:
            async def chunks() -> AsyncIterator[bytes]:
                yield b"hello"
                yield b" stream"

            return chunks()

    @Module(controllers=[StreamController])
    class AppModule:
        pass

    with TestClient(cast(Any, create_app(AppModule))) as client:
        response = client.get("/streams")

    assert response.status_code == 200
    assert response.text == "HELLO STREAM"