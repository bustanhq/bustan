"""Conversion from the framework's neutral responses into Starlette's own."""

from __future__ import annotations

from starlette.responses import FileResponse, Response, StreamingResponse

from ...contracts import HttpFileResponse, HttpResponse, HttpStreamResponse


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


__all__ = ("to_starlette_response",)
