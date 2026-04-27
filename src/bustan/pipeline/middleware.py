"""Middleware abstractions and route-matching helpers."""

from __future__ import annotations

import fnmatch
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Protocol, cast

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

CallNext = Callable[[Request], Awaitable[Response]]


class MiddlewareHandler(Protocol):
    def __call__(self, request: Request, call_next: CallNext) -> Awaitable[Response] | Response: ...


class Middleware:
    """Base class for request middleware."""

    async def use(self, request: Request, call_next: CallNext) -> Response:
        return await call_next(request)


@dataclass(slots=True)
class MiddlewareBinding:
    """One middleware registration collected from module configuration."""

    middlewares: list[object] = field(default_factory=list)
    routes: list[str] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)


class MiddlewareRegistration:
    """Fluent middleware registration builder."""

    def __init__(self, binding: MiddlewareBinding) -> None:
        self._binding = binding

    def for_routes(self, *routes: str) -> MiddlewareRegistration:
        self._binding.routes.extend(routes)
        return self

    def exclude(self, *routes: str) -> MiddlewareRegistration:
        self._binding.excluded.extend(routes)
        return self


class MiddlewareConsumer:
    """Collect middleware bindings from module configuration callbacks."""

    def __init__(self) -> None:
        self.bindings: list[MiddlewareBinding] = []

    def apply(self, *middlewares: object) -> MiddlewareRegistration:
        binding = MiddlewareBinding(middlewares=list(middlewares))
        self.bindings.append(binding)
        return MiddlewareRegistration(binding)


def path_matches(path: str, patterns: list[str]) -> bool:
    """Return whether the path matches any glob patterns."""
    if not patterns:
        return True
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


class ConditionalMiddleware(BaseHTTPMiddleware):
    """Starlette adapter that conditionally runs a Bustan middleware."""

    def __init__(
        self,
        app,
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

        if hasattr(self._handler, "use"):
            result = cast(Middleware, self._handler).use(request, call_next)
        else:
            result = cast(MiddlewareHandler, self._handler)(request, call_next)

        if inspect.isawaitable(result):
            return await cast(Awaitable[Response], result)
        return result
