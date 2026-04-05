"""Exception filter base class and resolution helpers."""

from __future__ import annotations

import inspect

from .context import RequestContext


class ExceptionFilter:
    """Base class for mapping exceptions to handler results.

    Override exception_types to declare which exception classes this filter can
    handle.
    """

    exception_types: tuple[type[BaseException], ...] = (Exception,)

    async def catch(self, exc: Exception, context: RequestContext) -> object:
        """Convert an exception into a handler result or response payload."""

        raise exc


async def handle_exception(
    context: RequestContext,
    exc: Exception,
    filters: tuple[ExceptionFilter, ...],
) -> object | None:
    """Return the first filter result that handles the supplied exception."""

    for exception_filter in reversed(filters):
        if not isinstance(exc, exception_filter.exception_types):
            continue

        result = exception_filter.catch(exc, context)
        if inspect.isawaitable(result):
            return await result
        return result

    return None