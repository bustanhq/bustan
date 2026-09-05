"""Adapter-neutral response coercion helpers."""

from __future__ import annotations

from collections.abc import AsyncIterable, Iterable
from dataclasses import asdict, is_dataclass
from os import PathLike
from pathlib import Path
from typing import Protocol, cast

from ...contracts import (
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
        return HttpResponse.json(asdict(value))

    if isinstance(value, (dict, list)):
        return HttpResponse.json(value)

    if isinstance(value, NativeHttpResponse):
        return value

    raise TypeError(f"Unsupported handler return type: {type(value).__name__}")


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
    # Every response the framework writes carries a status and headers, whether the
    # framework built it or a handler returned its transport's own, so the plan is
    # applied the same way to both.
    if response.status_code == 200:
        response.status_code = response_plan.default_status_code
    for header_name, header_value in response_plan.headers:
        response.headers.setdefault(header_name, header_value)
    return response


__all__ = [
    "CoercedResponse",
    "DefaultResponseSerializer",
    "ResponseHandler",
    "ResponseSerializer",
    "coerce_response",
]
