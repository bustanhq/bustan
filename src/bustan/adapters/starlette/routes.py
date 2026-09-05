"""Registration of neutral adapter routes as Starlette routes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from .requests import StarletteHttpRequest
from .responses import to_starlette_response

if TYPE_CHECKING:
    from collections.abc import Sequence

    from starlette.routing import BaseRoute

    from ...contracts import AdapterRoute


def build_starlette_routes(routes: Sequence[AdapterRoute]) -> list[BaseRoute]:
    """Turn neutral adapter routes into the Starlette routes that serve them.

    A route the framework already built in Starlette's own terms is taken as it
    stands; every other one is served by an endpoint that converts the request into
    the neutral contract, awaits the framework's handler and writes the result back.
    """

    built: list[BaseRoute] = []
    for route in routes:
        registration = route.registration
        if isinstance(registration, Route):
            built.append(registration)
            continue
        starlette_route = Route(
            path=route.path,
            endpoint=_build_endpoint(route),
            methods=list(route.methods),
            name=route.name,
        )
        for attribute, value in route.attributes:
            setattr(starlette_route, attribute, value)
        built.append(starlette_route)
    return built


def _build_endpoint(route: AdapterRoute):
    handler = route.handler
    if handler is None:
        raise ValueError(f"Route {route.path} carries neither a handler nor a registration")

    async def endpoint(request: Request) -> Response:
        return to_starlette_response(await handler(StarletteHttpRequest(request)))

    endpoint.__name__ = route.name or "endpoint"
    return endpoint


__all__ = ("build_starlette_routes",)
