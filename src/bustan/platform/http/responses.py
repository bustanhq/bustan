"""Adapter-neutral response coercion helpers."""

from __future__ import annotations

from collections.abc import AsyncIterable, Iterable
from dataclasses import asdict, is_dataclass
from os import PathLike
from pathlib import Path
from typing import Protocol, cast

from starlette.responses import Response

from .abstractions import HttpFileResponse, HttpResponse, HttpStreamResponse
from .compiler import ResponsePlan, ResponseStrategy


class ResponseSerializer(Protocol):
	"""Serializer contract used by the response handler."""

	def serialize(self, value: object) -> HttpResponse | Response:
		pass


class DefaultResponseSerializer:
	"""Serialize common Python values into adapter-neutral HTTP responses."""

	def serialize(self, value: object) -> HttpResponse | Response:
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
	) -> HttpResponse | HttpStreamResponse | HttpFileResponse | Response:
		if response_plan.strategy is ResponseStrategy.RAW:
			response = _coerce_raw_response(result)
		elif response_plan.strategy is ResponseStrategy.STREAM:
			response = _coerce_stream_response(result)
		elif response_plan.strategy is ResponseStrategy.FILE:
			response = _coerce_file_response(result)
		else:
			response = self._serializer.serialize(result)

		return _apply_response_plan(response, response_plan)


def coerce_response(value: object) -> HttpResponse | Response:
	"""Convert common handler return values into abstract HTTP responses."""

	if isinstance(value, Response):
		return value

	if isinstance(value, HttpResponse):
		return value

	if value is None:
		return HttpResponse.empty()

	if is_dataclass(value) and not isinstance(value, type):
		return HttpResponse.json(asdict(value))

	if isinstance(value, (dict, list)):
		return HttpResponse.json(value)

	raise TypeError(f"Unsupported handler return type: {type(value).__name__}")


def _coerce_raw_response(
	value: object,
) -> HttpResponse | HttpStreamResponse | HttpFileResponse | Response:
	if isinstance(value, (Response, HttpResponse, HttpStreamResponse, HttpFileResponse)):
		return value
	raise TypeError(f"Unsupported raw response type: {type(value).__name__}")


def _coerce_stream_response(value: object) -> HttpStreamResponse | Response:
	if isinstance(value, Response):
		return value
	if isinstance(value, HttpStreamResponse):
		return value
	if isinstance(value, (bytes, str, dict, list)):
		raise TypeError(f"Unsupported stream response type: {type(value).__name__}")
	if isinstance(value, Iterable) or isinstance(value, AsyncIterable):
		return HttpStreamResponse(
			body=cast(Iterable[bytes] | AsyncIterable[bytes], value)
		)
	raise TypeError(f"Unsupported stream response type: {type(value).__name__}")


def _coerce_file_response(value: object) -> HttpFileResponse | Response:
	if isinstance(value, Response):
		return value
	if isinstance(value, HttpFileResponse):
		return value
	if isinstance(value, (str, PathLike, Path)):
		return HttpFileResponse(path=cast(str | PathLike[str], value))
	raise TypeError(f"Unsupported file response type: {type(value).__name__}")


def _apply_response_plan(
	response: HttpResponse | HttpStreamResponse | HttpFileResponse | Response,
	response_plan: ResponsePlan,
) -> HttpResponse | HttpStreamResponse | HttpFileResponse | Response:
	if isinstance(response, Response):
		if response.status_code == 200:
			response.status_code = response_plan.default_status_code
		for header_name, header_value in response_plan.headers:
			response.headers.setdefault(header_name, header_value)
		return response

	if response.status_code == 200:
		response.status_code = response_plan.default_status_code
	for header_name, header_value in response_plan.headers:
		response.headers.setdefault(header_name, header_value)
	return response


__all__ = [
	"DefaultResponseSerializer",
	"ResponseHandler",
	"ResponseSerializer",
	"coerce_response",
]
