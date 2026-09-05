"""Adapter-neutral response value types.

A handler's result is turned into one of these before any transport sees it, so the
same response can be written by any adapter and asserted on in a test with no server
running.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterable, Iterable, Mapping, MutableMapping
from dataclasses import dataclass, field
from os import PathLike


@dataclass(slots=True)
class HttpResponse:
    """Adapter-neutral mutable HTTP response container."""

    status_code: int = 200
    headers: MutableMapping[str, str] = field(default_factory=dict)
    body: bytes = b""
    media_type: str | None = None

    def set_body(self, body: bytes | str) -> None:
        """Replace the body, encoding text as UTF-8."""

        self.body = body.encode("utf-8") if isinstance(body, str) else body

    async def send(self, body: bytes | str) -> None:
        """Replace the body from an awaiting caller; the response is written later."""

        self.set_body(body)

    @classmethod
    def empty(cls, *, status_code: int = 204) -> HttpResponse:
        """Return a response with no body, defaulting to ``204 No Content``."""

        return cls(status_code=status_code, body=b"")

    @classmethod
    def json(
        cls,
        payload: object,
        *,
        status_code: int = 200,
        headers: Mapping[str, str] | None = None,
    ) -> HttpResponse:
        """Return a JSON response serialised without insignificant whitespace."""

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


__all__ = (
    "HttpFileResponse",
    "HttpResponse",
    "HttpStreamResponse",
)
