"""Registration of neutral adapter routes as Starlette routes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.requests import Request
from starlette.routing import Route

from .requests import StarletteHttpRequest
from .responses import write_response

if TYPE_CHECKING:
    from collections.abc import Sequence

    from starlette.routing import BaseRoute
    from starlette.types import Receive, Scope, Send

    from ...contracts import AdapterRoute, RouteHandler


def build_starlette_routes(routes: Sequence[AdapterRoute]) -> list[BaseRoute]:
    """Turn neutral adapter routes into the Starlette routes that serve them.

    Every route is served by an endpoint that converts the request into the neutral
    contract, awaits the framework's handler and writes the result back.
    """

    built: list[BaseRoute] = []
    for route in routes:
        if route.handler is None:
            raise ValueError(f"Route {route.path} carries no handler")
        starlette_route = Route(
            path=route.path,
            endpoint=_RouteEndpoint(route.handler),
            methods=list(route.methods),
            # Starlette names a route given no name after its endpoint, which would make
            # the private class below the name of every unnamed route.
            name=route.name or "endpoint",
        )
        for attribute, value in route.attributes:
            setattr(starlette_route, attribute, value)
        built.append(starlette_route)
    return built


class _RouteEndpoint:
    """Serve one route as an ASGI application: one request in, one response out.

    Starlette hands an endpoint written as a function to a request-response wrapper,
    which builds closures around every call and runs it inside a second
    exception-handling layer, whose sender every message of the response then passes
    through. A route here needs neither. The framework's handler answers a failure
    through the framework's own error model before it can leave the route, and the
    application's exception middleware stands around every route regardless, holding the
    same handlers the inner layer would have consulted. Starlette calls an endpoint that
    is not a function as the ASGI application it is, so this one builds the Starlette
    request the handler reads and writes the response straight to the server.
    """

    __slots__ = ("_handler",)

    def __init__(self, handler: RouteHandler) -> None:
        self._handler = handler

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        request = Request(scope, receive, send)
        result = await self._handler(StarletteHttpRequest(request))
        await write_response(result, scope, receive, send)


__all__ = ("build_starlette_routes",)
