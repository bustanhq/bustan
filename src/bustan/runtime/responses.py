"""Adapter-neutral response coercion helpers."""

from __future__ import annotations

import json
from collections.abc import AsyncIterable, Iterable
from dataclasses import asdict, is_dataclass
from os import PathLike
from pathlib import Path
from typing import Protocol, cast

import msgspec

from ..contracts import (
    HttpFileResponse,
    HttpResponse,
    HttpStreamResponse,
    NativeHttpResponse,
)
from .compiler import ResponsePlan, ResponseStrategy

CoercedResponse = HttpResponse | HttpStreamResponse | HttpFileResponse | NativeHttpResponse


class ResponseSerializer(Protocol):
    """Serializer contract used by the response handler."""

    def serialize(self, value: object) -> HttpResponse | NativeHttpResponse:
        pass


class DefaultResponseSerializer:
    """Serialize common Python values into adapter-neutral HTTP responses."""

    def serialize(self, value: object) -> HttpResponse | NativeHttpResponse:
        return coerce_response(value)


class ResponseHandler:
    """Centralized runtime writer for controller return values."""

    def __init__(self, serializer: ResponseSerializer | None = None) -> None:
        self._serializer = serializer or DefaultResponseSerializer()

    def write(
        self,
        *,
        result: object,
        response_plan: ResponsePlan,
    ) -> CoercedResponse:
        if response_plan.strategy is ResponseStrategy.RAW:
            response = _coerce_raw_response(result)
        elif response_plan.strategy is ResponseStrategy.STREAM:
            response = _coerce_stream_response(result)
        elif response_plan.strategy is ResponseStrategy.FILE:
            response = _coerce_file_response(result)
        else:
            response = self._serializer.serialize(result)

        return _apply_response_plan(response, response_plan)


def coerce_response(value: object) -> HttpResponse | NativeHttpResponse:
    """Convert common handler return values into abstract HTTP responses."""

    if isinstance(value, HttpResponse):
        return value

    if value is None:
        return HttpResponse.empty()

    if is_dataclass(value) and not isinstance(value, type):
        return _json_response(asdict(value))

    if isinstance(value, (dict, list)):
        return _json_response(value)

    if isinstance(value, NativeHttpResponse):
        return value

    raise TypeError(f"Unsupported handler return type: {type(value).__name__}")


def _json_response(payload: object) -> HttpResponse:
    # The response HttpResponse.json builds, with the body encoded by msgspec, which writes
    # a hundred-item body several times faster than json.dumps. Where json.dumps writes a
    # value, msgspec writes the same text except in three ways: NaN and Infinity become
    # null, and a non-finite key becomes "nan", "inf" or "-inf"; a float takes msgspec's
    # spelling, 1e16, 1e-7 or 0.000015 for 1e+16, 1e-07 or 1.5e-05; and a container is
    # written in the order it stores its members, where json.dumps follows an OrderedDict
    # reordered by move_to_end or a subclass overriding items() or __iter__. Otherwise
    # msgspec raises, or writes a character past "~" that json.dumps escapes, and json.dumps
    # writes the body instead. It asks msgspec for each value it cannot write itself, so a
    # datetime, a UUID or any other value only msgspec encodes is written the same in either
    # body, while a key json.dumps cannot write still raises.
    try:
        body = msgspec.json.encode(payload)
    except Exception:
        body = None
    if body is None or not body.isascii() or b"\x7f" in body:
        text = json.dumps(payload, separators=(",", ":"), default=msgspec.to_builtins)
        body = text.encode("utf-8")
    return HttpResponse(body=body, media_type="application/json")


def _coerce_raw_response(value: object) -> CoercedResponse:
    if isinstance(value, (HttpResponse, HttpStreamResponse, HttpFileResponse)):
        return value
    if isinstance(value, NativeHttpResponse):
        return value
    raise TypeError(f"Unsupported raw response type: {type(value).__name__}")


def _coerce_stream_response(value: object) -> HttpStreamResponse | NativeHttpResponse:
    if isinstance(value, HttpStreamResponse):
        return value
    if isinstance(value, (bytes, str, dict, list)):
        raise TypeError(f"Unsupported stream response type: {type(value).__name__}")
    if isinstance(value, NativeHttpResponse):
        return value
    if isinstance(value, Iterable | AsyncIterable):
        return HttpStreamResponse(body=cast(Iterable[bytes] | AsyncIterable[bytes], value))
    raise TypeError(f"Unsupported stream response type: {type(value).__name__}")


def _coerce_file_response(value: object) -> HttpFileResponse | NativeHttpResponse:
    if isinstance(value, HttpFileResponse):
        return value
    if isinstance(value, (str, PathLike, Path)):
        return HttpFileResponse(path=cast(str | PathLike[str], value))
    if isinstance(value, NativeHttpResponse):
        return value
    raise TypeError(f"Unsupported file response type: {type(value).__name__}")


def _apply_response_plan(
    response: CoercedResponse,
    response_plan: ResponsePlan,
) -> CoercedResponse:
    # Every response the framework writes carries a status, whether the framework built
    # it or a handler returned its transport's own, so the plan is applied the same way
    # to both.
    if response.status_code == 200:
        response.status_code = response_plan.default_status_code
    return response


__all__ = [
    "CoercedResponse",
    "DefaultResponseSerializer",
    "ResponseHandler",
    "ResponseSerializer",
    "coerce_response",
]
