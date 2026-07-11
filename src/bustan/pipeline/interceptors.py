"""Interceptor base class and chain execution helpers."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Protocol, cast

from .context import ExecutionContext

CallNext = Callable[[], Awaitable[object]]


class CallHandler(Protocol):
    """Public continuation contract for interceptor chaining."""

    async def handle(self) -> object:
        """Resume the next link in the interceptor chain."""


class _CallableCallHandler:
    """Adapt an async callable into the public CallHandler contract."""

    def __init__(self, handler: CallNext) -> None:
        self._handler = handler

    async def handle(self) -> object:
        return await self._handler()

    async def __call__(self) -> object:
        return await self.handle()


class Interceptor:
    """Base class for around-handler behaviors."""

    mutates_response_body = False

    async def intercept(self, context: ExecutionContext, next: CallHandler) -> object:
        """Wrap handler execution and optionally transform the result."""

        return await next.handle()


async def call_with_interceptors(
    context: ExecutionContext,
    interceptors: tuple[Interceptor, ...],
    final_handler: CallNext | CallHandler,
) -> object:
    """Execute a handler through a nested interceptor chain."""

    terminal_handler = _as_call_handler(final_handler)

    async def invoke(index: int) -> object:
        if index >= len(interceptors):
            return await terminal_handler.handle()

        # Each interceptor decides when, or whether, the next link in the
        # chain executes by controlling the call_next callback.
        interceptor = interceptors[index]
        result = interceptor.intercept(context, _CallableCallHandler(lambda: invoke(index + 1)))
        if inspect.isawaitable(result):
            return await result
        return result

    return await invoke(0)


def _as_call_handler(handler: CallNext | CallHandler) -> CallHandler:
    if isinstance(handler, _CallableCallHandler):
        return handler
    if callable(getattr(handler, "handle", None)):
        return cast(CallHandler, handler)
    return _CallableCallHandler(cast(CallNext, handler))


__all__ = ["CallHandler", "Interceptor", "call_with_interceptors"]
