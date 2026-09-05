"""Starlette middleware that runs one Bustan middleware for matching paths."""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, cast

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from ...contracts import HttpRequest
from ...pipeline.middleware import Middleware, MiddlewareHandler, path_matches
from .requests import StarletteHttpRequest
from .responses import to_starlette_response

if TYPE_CHECKING:
    from starlette.types import ASGIApp


class ConditionalMiddleware(BaseHTTPMiddleware):
    """Run one Bustan middleware around the requests whose path it applies to.

    The wrapped middleware is written against the neutral request contract, so this
    converts in both directions: the request on the way in, and whatever the
    middleware returns, or the transport's own response when the middleware simply
    passed the call through.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        handler: object,
        include: tuple[str, ...] = (),
        exclude: tuple[str, ...] = (),
    ) -> None:
        super().__init__(app)
        self._handler = handler
        self._include = list(include)
        self._exclude = list(exclude)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not path_matches(request.url.path, self._include):
            return await call_next(request)
        if self._exclude and path_matches(request.url.path, self._exclude):
            return await call_next(request)

        async def continue_chain(next_request: HttpRequest) -> object:
            native = next_request.native_request
            return await call_next(cast(Request, native))

        neutral_request = StarletteHttpRequest(request)
        if hasattr(self._handler, "use"):
            result = cast(Middleware, self._handler).use(neutral_request, continue_chain)
        else:
            result = cast(MiddlewareHandler, self._handler)(neutral_request, continue_chain)

        if inspect.isawaitable(result):
            result = await result
        return to_starlette_response(result)


__all__ = ("ConditionalMiddleware",)
