"""Adapter-neutral HTTP request and response abstractions."""

from __future__ import annotations

import json
from collections.abc import AsyncIterable, Iterable, Mapping, MutableMapping
from dataclasses import dataclass, field
from os import PathLike
from typing import Any, Protocol, cast, runtime_checkable

from starlette.requests import Request
from starlette.responses import FileResponse, Response, StreamingResponse


@dataclass(frozen=True, slots=True)
class HttpClientInfo:
    """Normalized client connection details."""

    host: str | None = None
    port: int | None = None


@runtime_checkable
class HttpUrl(Protocol):
    """Minimal URL surface required by the framework runtime."""

    @property
    def path(self) -> str:
        raise NotImplementedError


@runtime_checkable
class HttpQueryParams(Protocol):
    """Minimal multi-value query parameter surface used by parameter binding."""

    def getlist(self, key: str) -> list[str]:
        raise NotImplementedError

    def __contains__(self, key: object) -> bool:
        raise NotImplementedError

    def __getitem__(self, key: str) -> str:
        raise NotImplementedError


@runtime_checkable
class HttpFormData(Protocol):
    """Minimal form-data surface used by parameter binding."""

    def get(self, key: str, default: object | None = None) -> object | None:
        raise NotImplementedError

    def getlist(self, key: str) -> list[object]:
        raise NotImplementedError


@runtime_checkable
class HttpRequest(Protocol):
    """Adapter-neutral request surface used by framework runtime code."""

    @property
    def native_request(self) -> object:
        raise NotImplementedError

    @property
    def method(self) -> str:
        raise NotImplementedError

    @property
    def path(self) -> str:
        raise NotImplementedError

    @property
    def url(self) -> HttpUrl:
        raise NotImplementedError

    @property
    def headers(self) -> Mapping[str, str]:
        raise NotImplementedError

    @property
    def query_params(self) -> HttpQueryParams:
        raise NotImplementedError

    @property
    def path_params(self) -> Mapping[str, str]:
        raise NotImplementedError

    @property
    def cookies(self) -> Mapping[str, str]:
        raise NotImplementedError

    @property
    def state(self) -> Any:
        raise NotImplementedError

    @property
    def client(self) -> HttpClientInfo | None:
        raise NotImplementedError

    @property
    def app(self) -> Any:
        raise NotImplementedError

    async def body(self) -> bytes:
        raise NotImplementedError

    async def json(self) -> object:
        raise NotImplementedError

    async def form(self) -> HttpFormData:
        raise NotImplementedError


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
    def state(self) -> Any:
        return self._request.state

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


@dataclass(slots=True)
class HttpResponse:
    """Adapter-neutral mutable HTTP response container."""

    status_code: int = 200
    headers: MutableMapping[str, str] = field(default_factory=dict)
    body: bytes = b""
    media_type: str | None = None

    def set_body(self, body: bytes | str) -> None:
        self.body = body.encode("utf-8") if isinstance(body, str) else body

    async def send(self, body: bytes | str) -> None:
        self.set_body(body)

    @classmethod
    def empty(cls, *, status_code: int = 204) -> HttpResponse:
        return cls(status_code=status_code, body=b"")

    @classmethod
    def json(
        cls,
        payload: object,
        *,
        status_code: int = 200,
        headers: Mapping[str, str] | None = None,
    ) -> HttpResponse:
        return cls(
            status_code=status_code,
            headers=dict(headers or {}),
            body=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            media_type="application/json",
        )


@dataclass(slots=True)
class HttpStreamResponse:
    """Adapter-neutral streaming HTTP response container."""

    body: Iterable[bytes] | AsyncIterable[bytes]
    status_code: int = 200
    headers: MutableMapping[str, str] = field(default_factory=dict)
    media_type: str | None = None


@dataclass(slots=True)
class HttpFileResponse:
    """Adapter-neutral file HTTP response container."""

    path: str | PathLike[str]
    status_code: int = 200
    headers: MutableMapping[str, str] = field(default_factory=dict)
    media_type: str | None = None
    filename: str | None = None


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
