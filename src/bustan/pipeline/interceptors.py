"""Interceptor base class and chain execution helpers."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable

from .context import HandlerContext

CallNext = Callable[[], Awaitable[object]]


class Interceptor:
    """Base class for around-handler behaviors."""

    async def intercept(self, context: HandlerContext, call_next: CallNext) -> object:
        """Wrap handler execution and optionally transform the result."""

        return await call_next()


async def call_with_interceptors(
    context: HandlerContext,
    interceptors: tuple[Interceptor, ...],
    final_handler: CallNext,
) -> object:
    """Execute a handler through a nested interceptor chain."""

    async def invoke(index: int) -> object:
        if index >= len(interceptors):
            return await final_handler()

        # Each interceptor decides when, or whether, the next link in the
        # chain executes by controlling the call_next callback.
        interceptor = interceptors[index]
        result = interceptor.intercept(context, lambda: invoke(index + 1))
        if inspect.isawaitable(result):
            return await result
        return result

    return await invoke(0)
