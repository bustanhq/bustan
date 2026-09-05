"""The Starlette middleware wrapper bridges a neutral middleware into the transport."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from starlette.requests import Request
from starlette.responses import Response

from bustan.adapters.starlette import ConditionalMiddleware
from bustan.contracts import HttpRequest, HttpResponse
from bustan.pipeline.middleware import Middleware

if TYPE_CHECKING:
    from tests.conftest import RequestFactory


async def _unreachable_app(scope, receive, send) -> None:
    """Stand in for the rest of the stack; every test here stops before it."""

    raise AssertionError("the wrapped application must not be reached")


@pytest.mark.anyio
async def test_dispatch_covers_sync_and_bypass_paths(build_request: RequestFactory) -> None:
    events: list[str] = []

    def sync_handler(request: HttpRequest, call_next) -> HttpResponse:
        events.append("handled")
        return HttpResponse(status_code=201, body=b"handled")

    middleware = ConditionalMiddleware(
        _unreachable_app,
        handler=sync_handler,
        include=("/users/*",),
    )

    async def call_next(current_request: Request) -> Response:
        events.append("next")
        return Response(content=b"next", status_code=200)

    handled_response = await middleware.dispatch(build_request(path="/users/123"), call_next)
    bypass_response = await middleware.dispatch(build_request(path="/health"), call_next)

    assert handled_response.status_code == 201
    assert bypass_response.status_code == 200
    assert events == ["handled", "next"]


@pytest.mark.anyio
async def test_an_excluded_path_reaches_the_rest_of_the_chain(
    build_request: RequestFactory,
) -> None:
    async def call_next(current_request: Request) -> Response:
        return Response(content=b"next", status_code=200)

    request = build_request(path="/users/skip")

    class AsyncMiddleware(Middleware):
        async def use(self, request: HttpRequest, call_next) -> HttpResponse:
            return HttpResponse(status_code=202, body=b"middleware")

    middleware = ConditionalMiddleware(
        _unreachable_app,
        handler=AsyncMiddleware(),
        include=("/users/*",),
        exclude=("/users/skip",),
    )

    excluded_response = await middleware.dispatch(request, call_next)
    handled_response = await middleware.dispatch(build_request(path="/users/run"), call_next)

    assert excluded_response.status_code == 200
    assert handled_response.status_code == 202


@pytest.mark.anyio
async def test_a_middleware_that_passes_through_returns_the_transport_response(
    build_request: RequestFactory,
) -> None:
    async def call_next(current_request: Request) -> Response:
        return Response(content=b"next", status_code=204)

    middleware = ConditionalMiddleware(
        _unreachable_app,
        handler=Middleware(),
        include=("/users/*",),
    )

    response = await middleware.dispatch(build_request(path="/users/1"), call_next)

    assert response.status_code == 204
