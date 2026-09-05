"""Starlette-flavoured request and response conversion, plus a transitional re-export.

The adapter-neutral types this module used to define now live in ``bustan.contracts``
and are re-exported below so that no importer had to change when they moved. That
re-export is temporary: ticket T-301 moves ``StarletteHttpRequest``,
``as_http_request`` and ``to_starlette_response`` into the Starlette adapter package
and deletes this module along with the re-export.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from starlette.requests import Request
from starlette.responses import FileResponse, Response, StreamingResponse

from ...contracts import (
    HttpClientInfo,
    HttpFileResponse,
    HttpFormData,
    HttpQueryParams,
    HttpRequest,
    HttpRequestState,
    HttpResponse,
    HttpStreamResponse,
    HttpUrl,
)


class StarletteHttpRequest:
    """Adapter-neutral wrapper around a Starlette request instance."""

    def __init__(self, request: Request) -> None:
        self._request = request

    @property
    def native_request(self) -> Request:
        return self._request

    @property
    def method(self) -> str:
        return self._request.method

    @property
    def path(self) -> str:
        return self._request.url.path

    @property
    def url(self) -> HttpUrl:
        return self._request.url

    @property
    def headers(self) -> Mapping[str, str]:
        return self._request.headers

    @property
    def query_params(self) -> HttpQueryParams:
        return self._request.query_params

    @property
    def path_params(self) -> Mapping[str, str]:
        return self._request.path_params

    @property
    def cookies(self) -> Mapping[str, str]:
        return self._request.cookies

    @property
    def state(self) -> HttpRequestState:
        return cast(HttpRequestState, self._request.state)

    @property
    def client(self) -> HttpClientInfo | None:
        client = self._request.client
        if client is None:
            return None
        return HttpClientInfo(host=client.host, port=client.port)

    @property
    def app(self) -> Any:
        return self._request.app

    async def body(self) -> bytes:
        return await self._request.body()

    async def json(self) -> object:
        return await self._request.json()

    async def form(self) -> HttpFormData:
        return cast(HttpFormData, await self._request.form())


def as_http_request(request: HttpRequest | Request | object) -> HttpRequest:
    """Return an adapter-neutral request wrapper."""

    if isinstance(request, StarletteHttpRequest):
        return request
    if isinstance(request, Request):
        return StarletteHttpRequest(request)
    return cast(HttpRequest, request)


def to_starlette_response(
    value: HttpResponse | HttpStreamResponse | HttpFileResponse | Response,
) -> Response:
    """Convert an abstract response into a concrete Starlette response."""

    if isinstance(value, Response):
        return value

    if isinstance(value, HttpStreamResponse):
        return StreamingResponse(
            value.body,
            status_code=value.status_code,
            headers=dict(value.headers),
            media_type=value.media_type,
        )

    if isinstance(value, HttpFileResponse):
        return FileResponse(
            path=value.path,
            status_code=value.status_code,
            headers=dict(value.headers),
            media_type=value.media_type,
            filename=value.filename,
        )

    return Response(
        content=value.body,
        status_code=value.status_code,
        headers=dict(value.headers),
        media_type=value.media_type,
    )


__all__ = (
    "HttpClientInfo",
    "HttpFormData",
    "HttpQueryParams",
    "HttpRequest",
    "HttpFileResponse",
    "HttpResponse",
    "HttpStreamResponse",
    "HttpUrl",
    "StarletteHttpRequest",
    "as_http_request",
    "to_starlette_response",
)
