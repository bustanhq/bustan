"""Fixtures shared by the whole test suite.

Two factories live here. ``build_request`` constructs a Starlette ``Request`` from
the parts a test actually cares about, and ``build_app`` constructs the Starlette
application a request is occasionally attached to. Both are exposed as fixtures
returning a callable rather than a built object, because a single test frequently
needs two or three requests that differ in one field.

Every parameter is keyword-only and has a default, so ``build_request()`` with no
arguments yields a bare ``GET /`` and each call site names only what it varies.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Protocol
from urllib.parse import urlencode

import pytest
from starlette.applications import Starlette
from starlette.requests import Request

if TYPE_CHECKING:
    from collections.abc import Sequence

    from starlette.routing import BaseRoute

_DEFAULT_HOST = (b"host", b"testserver")
_JSON_CONTENT_TYPE = "application/json"


class RequestFactory(Protocol):
    """Builds a Starlette request; see ``build_request`` for the parameter meanings."""

    def __call__(
        self,
        *,
        method: str = "GET",
        path: str = "/",
        path_params: dict[str, object] | None = None,
        query_params: dict[str, object] | None = None,
        headers: list[tuple[bytes, bytes]] | None = None,
        cookies: dict[str, str] | None = None,
        json_body: object | None = None,
        raw_body: bytes | None = None,
        content_type: str | None = None,
        app: Starlette | None = None,
    ) -> Request: ...


class AppFactory(Protocol):
    """Builds a Starlette application; see ``build_app`` for the parameter meanings."""

    def __call__(self, *, routes: Sequence[BaseRoute] | None = None) -> Starlette: ...


def _build_headers(
    headers: list[tuple[bytes, bytes]] | None,
    cookies: dict[str, str] | None,
    content_type: str | None,
) -> list[tuple[bytes, bytes]]:
    """Assemble the raw ASGI header list, guaranteeing exactly one host header."""

    assembled = list(headers or [])
    if not any(name.lower() == b"host" for name, _value in assembled):
        assembled.insert(0, _DEFAULT_HOST)
    if content_type is not None:
        assembled.append((b"content-type", content_type.encode("utf-8")))
    if cookies:
        cookie_header = "; ".join(f"{name}={value}" for name, value in cookies.items())
        assembled.append((b"cookie", cookie_header.encode("utf-8")))
    return assembled


def _build_query_string(path: str, query_params: dict[str, object] | None) -> tuple[str, bytes]:
    """Split a query string off ``path`` and merge it with ``query_params``."""

    path_only, _, inline_query = path.partition("?")
    encoded = urlencode(query_params or {}, doseq=True)
    merged = "&".join(part for part in (inline_query, encoded) if part)
    return path_only, merged.encode("utf-8")


def _build_body(json_body: object | None, raw_body: bytes | None) -> bytes:
    """Serialise whichever body form the caller supplied; ``json_body`` wins."""

    if json_body is not None:
        return json.dumps(json_body).encode("utf-8")
    if raw_body is not None:
        return raw_body
    return b""


@pytest.fixture
def build_request() -> RequestFactory:
    """Return a factory for Starlette requests.

    The factory accepts ``method``, ``path`` (a query string may be embedded in it),
    ``path_params``, ``query_params``, ``headers`` as raw ASGI byte pairs, ``cookies``,
    a ``json_body`` to serialise or a ``raw_body`` to send verbatim, an explicit
    ``content_type`` and an ``app`` to place in the scope. A body implies a JSON
    content type unless ``content_type`` says otherwise. The request body is delivered
    once; every later receive reports an empty final chunk, as a real server does.
    """

    def factory(
        *,
        method: str = "GET",
        path: str = "/",
        path_params: dict[str, object] | None = None,
        query_params: dict[str, object] | None = None,
        headers: list[tuple[bytes, bytes]] | None = None,
        cookies: dict[str, str] | None = None,
        json_body: object | None = None,
        raw_body: bytes | None = None,
        content_type: str | None = None,
        app: Starlette | None = None,
    ) -> Request:
        has_body = json_body is not None or raw_body is not None
        if content_type is None and has_body:
            content_type = _JSON_CONTENT_TYPE
        body = _build_body(json_body, raw_body)
        path_only, query_string = _build_query_string(path, query_params)

        scope: dict[str, object] = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path_only,
            "raw_path": path_only.encode("utf-8"),
            "query_string": query_string,
            "headers": _build_headers(headers, cookies, content_type),
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
            "path_params": path_params or {},
        }
        if app is not None:
            scope["app"] = app

        body_sent = False

        async def receive() -> dict[str, object]:
            nonlocal body_sent
            if body_sent:
                return {"type": "http.request", "body": b"", "more_body": False}
            body_sent = True
            return {"type": "http.request", "body": body, "more_body": False}

        return Request(scope, receive)

    return factory


@pytest.fixture
def build_app() -> AppFactory:
    """Return a factory for bare Starlette applications, optionally carrying ``routes``."""

    def factory(*, routes: Sequence[BaseRoute] | None = None) -> Starlette:
        return Starlette(routes=list(routes) if routes is not None else None)

    return factory
