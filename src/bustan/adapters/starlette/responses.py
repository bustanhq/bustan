"""The framework's neutral responses, converted into Starlette's own or written directly."""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.responses import FileResponse, Response, StreamingResponse

from ...contracts import HttpFileResponse, HttpResponse, HttpStreamResponse

if TYPE_CHECKING:
    from starlette.types import Receive, Scope, Send


def to_starlette_response(value: object) -> Response:
    """Convert a framework response into the Starlette response that writes it.

    A handler that returned a Starlette response of its own is passed through
    unchanged, because the framework has nothing to add to a response the transport
    already built.
    """

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

    if isinstance(value, HttpResponse):
        return Response(
            content=value.body,
            status_code=value.status_code,
            headers=dict(value.headers),
            media_type=value.media_type,
        )

    raise TypeError(f"Cannot write {type(value).__name__} as a Starlette response")


async def write_response(value: object, scope: Scope, receive: Receive, send: Send) -> None:
    """Write a framework response to the server.

    A plain response with a body already in bytes is sent as the two messages Starlette's
    own response would send, carrying the headers it would render, without that response
    being built first: a route would otherwise build one for every request only to read
    it once. Only the framework's own class is written this way, because a subclass may
    compute what the fields hold. Everything else is converted and written by Starlette.
    """

    if type(value) is HttpResponse and type(value.body) is bytes:
        await send(
            {
                "type": "http.response.start",
                "status": value.status_code,
                "headers": _raw_headers(value),
            }
        )
        await send({"type": "http.response.body", "body": value.body})
        return
    await to_starlette_response(value)(scope, receive, send)


def _raw_headers(response: HttpResponse) -> list[tuple[bytes, bytes]]:
    """Return a plain response's headers as Starlette's response renders them.

    Every name is lower-cased and both halves are encoded as Latin-1, in the order the
    response holds them. A content length follows unless the response set one or its
    status is one Starlette sends no length for: below 200, 204 or 304. The media type
    follows as the content type unless the response set one, and a text type that names
    no charset is given UTF-8.
    """

    raw = [
        (name.lower().encode("latin-1"), value.encode("latin-1"))
        for name, value in response.headers.items()
    ]
    present = {name for name, _value in raw}
    status = response.status_code
    if b"content-length" not in present and not (status < 200 or status in (204, 304)):
        raw.append((b"content-length", str(len(response.body)).encode("latin-1")))
    media_type = response.media_type
    if media_type is not None and b"content-type" not in present:
        if media_type.startswith("text/") and "charset=" not in media_type.lower():
            media_type = f"{media_type}; charset=utf-8"
        raw.append((b"content-type", media_type.encode("latin-1")))
    return raw


__all__ = ("to_starlette_response", "write_response")
