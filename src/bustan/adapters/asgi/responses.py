"""The responses this transport writes, and the conversion into them.

Raw ASGI has no response object of its own: a response is a ``http.response.start``
message followed by one or more ``http.response.body`` messages. These three classes are
this adapter's own response objects, one per way of producing that sequence, and each
knows how to write itself to a ``send`` callable.
"""

from __future__ import annotations

import asyncio
import mimetypes
from collections.abc import AsyncIterable, Iterable, Mapping, MutableMapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, cast
from urllib.parse import quote

from ...contracts import HttpFileResponse, HttpResponse, HttpStreamResponse

if TYPE_CHECKING:
    from os import PathLike

    from .types import Send

# How much of a file is read before each chunk is written, so that serving a large file
# never holds all of it in memory.
FILE_CHUNK_SIZE = 64 * 1024

# A response with one of these statuses carries no body, so neither a length nor a
# content type is written for it.
_BODILESS_STATUSES = frozenset({204, 304})


def _render_headers(
    headers: Mapping[str, str],
    media_type: str | None,
    content_length: int | None,
) -> list[tuple[bytes, bytes]]:
    """Return the header block for one response, filling in what it did not set.

    A content type or length the caller supplied is left alone; the defaults derived
    from the response itself are only added where the caller supplied neither.
    """

    rendered = {name.lower(): value for name, value in headers.items()}
    if media_type is not None and "content-type" not in rendered:
        rendered["content-type"] = _with_charset(media_type)
    if content_length is not None and "content-length" not in rendered:
        rendered["content-length"] = str(content_length)
    return [(name.encode("latin-1"), value.encode("latin-1")) for name, value in rendered.items()]


def _with_charset(media_type: str) -> str:
    """Return *media_type* with the charset a textual response is written in."""

    if media_type.startswith("text/") and "charset=" not in media_type:
        return f"{media_type}; charset=utf-8"
    return media_type


def _as_bytes(chunk: bytes | str) -> bytes:
    return chunk.encode("utf-8") if isinstance(chunk, str) else chunk


@dataclass(slots=True)
class AsgiResponse:
    """A response whose whole body is already in memory."""

    status_code: int = 200
    headers: MutableMapping[str, str] = field(default_factory=dict)
    body: bytes = b""
    media_type: str | None = None

    async def __call__(self, send: Send) -> None:
        """Write this response to one ASGI connection."""

        carries_body = self.status_code >= 200 and self.status_code not in _BODILESS_STATUSES
        body = self.body if carries_body else b""
        await send(
            {
                "type": "http.response.start",
                "status": self.status_code,
                "headers": _render_headers(
                    self.headers, self.media_type, len(body) if carries_body else None
                ),
            }
        )
        await send({"type": "http.response.body", "body": body, "more_body": False})


@dataclass(slots=True)
class AsgiStreamResponse:
    """A response whose body arrives in chunks, written as each one is produced.

    No content length is derived, because the number of bytes is not known until the
    last chunk has been produced; a caller that knows it sets the header itself.
    """

    body: Iterable[bytes] | AsyncIterable[bytes]
    status_code: int = 200
    headers: MutableMapping[str, str] = field(default_factory=dict)
    media_type: str | None = None

    async def __call__(self, send: Send) -> None:
        """Write this response to one ASGI connection, one chunk per message."""

        await send(
            {
                "type": "http.response.start",
                "status": self.status_code,
                "headers": _render_headers(self.headers, self.media_type, None),
            }
        )
        if isinstance(self.body, AsyncIterable):
            async for chunk in cast("AsyncIterable[bytes]", self.body):
                await send(
                    {"type": "http.response.body", "body": _as_bytes(chunk), "more_body": True}
                )
        else:
            for chunk in cast("Iterable[bytes]", self.body):
                await send(
                    {"type": "http.response.body", "body": _as_bytes(chunk), "more_body": True}
                )
        await send({"type": "http.response.body", "body": b"", "more_body": False})


@dataclass(slots=True)
class AsgiFileResponse:
    """A response whose body is the contents of a file on disk.

    The file is opened and its size read before the first message is written, so a
    missing file fails while the status can still say so rather than half way through a
    body that has already claimed ``200``. Reads happen on a worker thread, because the
    event loop serving every other connection must not block on disk.
    """

    path: str | PathLike[str]
    status_code: int = 200
    headers: MutableMapping[str, str] = field(default_factory=dict)
    media_type: str | None = None
    filename: str | None = None

    async def __call__(self, send: Send) -> None:
        """Write this response to one ASGI connection, one file chunk per message."""

        path = Path(self.path)
        size = await asyncio.to_thread(lambda: path.stat().st_size)
        await send(
            {
                "type": "http.response.start",
                "status": self.status_code,
                "headers": _render_headers(
                    {**self.headers, **self._disposition()}, self._type(), size
                ),
            }
        )
        with path.open("rb") as handle:
            while True:
                chunk = await asyncio.to_thread(handle.read, FILE_CHUNK_SIZE)
                if not chunk:
                    break
                await send({"type": "http.response.body", "body": chunk, "more_body": True})
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    def _type(self) -> str:
        if self.media_type is not None:
            return self.media_type
        guessed, _encoding = mimetypes.guess_type(self.filename or str(self.path))
        return guessed or "application/octet-stream"

    def _disposition(self) -> dict[str, str]:
        if self.filename is None:
            return {}
        # The plain form carries names a header can hold; the encoded form carries the
        # rest, and a client that understands only one of the two finds it here.
        return {
            "content-disposition": (
                f"attachment; filename=\"{self.filename}\"; filename*=utf-8''{quote(self.filename)}"
            )
        }


# Every response this transport can write.
AsgiResponseValue = AsgiResponse | AsgiStreamResponse | AsgiFileResponse


def to_asgi_response(value: object) -> AsgiResponseValue:
    """Convert a framework response into the response this transport writes.

    A response this adapter already produced is passed through unchanged, which is what
    a handler that returned one of them gets.
    """

    if isinstance(value, (AsgiResponse, AsgiStreamResponse, AsgiFileResponse)):
        return value

    if isinstance(value, HttpStreamResponse):
        return AsgiStreamResponse(
            body=value.body,
            status_code=value.status_code,
            headers=dict(value.headers),
            media_type=value.media_type,
        )

    if isinstance(value, HttpFileResponse):
        return AsgiFileResponse(
            path=value.path,
            status_code=value.status_code,
            headers=dict(value.headers),
            media_type=value.media_type,
            filename=value.filename,
        )

    if isinstance(value, HttpResponse):
        return AsgiResponse(
            status_code=value.status_code,
            headers=dict(value.headers),
            body=value.body,
            media_type=value.media_type,
        )

    raise TypeError(f"Cannot write {type(value).__name__} as an ASGI response")


def plain_text(body: str, *, status_code: int = 200, **headers: str) -> AsgiResponse:
    """Return the transport's own answer to a request no route handled."""

    return AsgiResponse(
        status_code=status_code,
        headers=dict(headers),
        body=body.encode("utf-8"),
        media_type="text/plain",
    )


__all__ = (
    "FILE_CHUNK_SIZE",
    "AsgiFileResponse",
    "AsgiResponse",
    "AsgiResponseValue",
    "AsgiStreamResponse",
    "plain_text",
    "to_asgi_response",
)
