"""Coerce common handler return values into Starlette responses."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass

from starlette.responses import JSONResponse, Response


def coerce_response(value: object) -> Response:
    """Convert a handler return value into a concrete Response instance."""

    if isinstance(value, Response):
        return value

    if value is None:
        return Response(status_code=204)

    if is_dataclass(value) and not isinstance(value, type):
        return JSONResponse(asdict(value))

    if isinstance(value, (dict, list)):
        return JSONResponse(value)

    raise TypeError(f"Unsupported handler return type: {type(value).__name__}")