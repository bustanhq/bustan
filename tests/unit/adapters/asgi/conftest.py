"""Fixtures for the raw ASGI adapter's tests.

An ASGI request is a scope and a receive callable rather than an object, so these two
factories build exactly that. Both are exposed as fixtures returning a callable, because
a single test frequently needs two requests that differ in one field.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

import pytest

if TYPE_CHECKING:
    from bustan.adapters.asgi.types import Message, Receive, Scope

_DEFAULT_HEADERS = [(b"host", b"testserver")]


class ScopeFactory(Protocol):
    """Builds an ASGI connection scope; see ``build_scope`` for the parameters."""

    def __call__(
        self,
        *,
        method: str = "GET",
        path: str = "/",
        query_string: bytes = b"",
        headers: list[tuple[bytes, bytes]] | None = None,
        client: tuple[str, int] | None = ("testclient", 50000),
        app: object | None = None,
    ) -> Scope:
        raise NotImplementedError


class ReceiveFactory(Protocol):
    """Builds a receive callable; see ``build_receive`` for the parameters."""

    def __call__(self, body: bytes = b"", *, chunks: int = 1) -> Receive:
        raise NotImplementedError


@pytest.fixture
def build_scope() -> ScopeFactory:
    """Return a factory for connection scopes, defaulting to a bare ``GET /``."""

    def factory(
        *,
        method: str = "GET",
        path: str = "/",
        query_string: bytes = b"",
        headers: list[tuple[bytes, bytes]] | None = None,
        client: tuple[str, int] | None = ("testclient", 50000),
        app: object | None = None,
    ) -> Scope:
        return {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": query_string,
            "root_path": "",
            "headers": _DEFAULT_HEADERS if headers is None else headers,
            "client": client,
            "server": ("testserver", 80),
            "app": app,
        }

    return factory


@pytest.fixture
def build_receive() -> ReceiveFactory:
    """Return a factory for receive callables that deliver *body* in *chunks* messages."""

    def factory(body: bytes = b"", *, chunks: int = 1) -> Receive:
        size = max(1, -(-len(body) // chunks))
        parts = [body[start : start + size] for start in range(0, len(body), size)] or [b""]
        messages: list[Message] = [
            {"type": "http.request", "body": part, "more_body": index < len(parts) - 1}
            for index, part in enumerate(parts)
        ]

        async def receive() -> Message:
            return messages.pop(0) if messages else {"type": "http.disconnect"}

        return receive

    return factory
