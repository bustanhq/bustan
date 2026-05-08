"""Unit tests for the interceptor runtime."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, cast

import pytest
from starlette.requests import Request
from starlette.responses import PlainTextResponse

from bustan import Controller, ExecutionContext, Get, Interceptor, Module, UseInterceptors, create_app
from bustan.core.errors import RouteDefinitionError
from bustan.pipeline.interceptors import (
    CallHandler,
    _CallableCallHandler,
    _as_call_handler,
    call_with_interceptors,
)


@pytest.mark.anyio
async def test_interceptors_execute_in_documented_order() -> None:
    events: list[str] = []
    context = _execution_context()

    class OuterInterceptor(Interceptor):
        async def intercept(self, context: ExecutionContext, next: CallHandler) -> object:
            events.append("outer:before")
            result = await next.handle()
            events.append("outer:after")
            return {"outer": result}

    class InnerInterceptor(Interceptor):
        async def intercept(self, context: ExecutionContext, next: CallHandler) -> object:
            events.append("inner:before")
            result = await next.handle()
            events.append("inner:after")
            return {"inner": result}

    async def final_handler() -> object:
        events.append("handler")
        return {"status": "ok"}

    result = await call_with_interceptors(
        context,
        (OuterInterceptor(), InnerInterceptor()),
        final_handler,
    )

    assert result == {"outer": {"inner": {"status": "ok"}}}
    assert events == [
        "outer:before",
        "inner:before",
        "handler",
        "inner:after",
        "outer:after",
    ]


@pytest.mark.anyio
async def test_streaming_handlers_remain_interceptable_without_eager_buffering() -> None:
    pulls: list[str] = []
    context = _execution_context()

    class UppercaseStreamInterceptor(Interceptor):
        async def intercept(self, context: ExecutionContext, next: CallHandler) -> object:
            stream = await next.handle()

            async def wrapped() -> AsyncIterator[bytes]:
                async for chunk in cast(AsyncIterator[bytes], stream):
                    pulls.append(f"chunk:{chunk.decode()}")
                    yield chunk.upper()

            return wrapped()

    async def source() -> AsyncIterator[bytes]:
        pulls.append("source:start")
        yield b"hello"
        pulls.append("source:middle")
        yield b" stream"
        pulls.append("source:end")

    async def final_handler() -> object:
        return source()

    result = await call_with_interceptors(context, (UppercaseStreamInterceptor(),), final_handler)

    assert pulls == []
    assert [chunk async for chunk in cast(AsyncIterator[bytes], result)] == [b"HELLO", b" STREAM"]
    assert pulls == [
        "source:start",
        "chunk:hello",
        "source:middle",
        "chunk: stream",
        "source:end",
    ]


def test_raw_response_incompatibilities_fail_before_execution() -> None:
    class EnvelopeInterceptor(Interceptor):
        mutates_response_body = True

        async def intercept(self, context: ExecutionContext, next: CallHandler) -> object:
            return {"data": await next.handle()}

    @UseInterceptors(EnvelopeInterceptor())
    @Controller("/users")
    class UsersController:
        @Get("/")
        def read_users(self) -> PlainTextResponse:
            return PlainTextResponse("ok")

    @Module(controllers=[UsersController])
    class AppModule:
        pass

    with pytest.raises(RouteDefinitionError, match="mutates the response body"):
        create_app(AppModule)


@pytest.mark.anyio
async def test_interceptor_helpers_cover_base_and_adapter_paths() -> None:
    context = _execution_context()

    async def final_handler() -> object:
        return "done"

    callable_handler = _CallableCallHandler(final_handler)

    assert await callable_handler() == "done"
    assert await Interceptor().intercept(context, callable_handler) == "done"
    assert _as_call_handler(callable_handler) is callable_handler

    class HandleOnly:
        async def handle(self) -> object:
            return "handled"

    handle_only = HandleOnly()

    assert _as_call_handler(handle_only) is handle_only
    assert await _as_call_handler(final_handler).handle() == "done"
    assert await call_with_interceptors(context, (), handle_only) == "handled"


def _execution_context() -> ExecutionContext:
    request = _build_request("/")

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
    )


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