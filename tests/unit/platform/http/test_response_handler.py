"""Unit tests for centralized response handling."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import cast

import pytest
from starlette.responses import Response

from bustan.platform.http.abstractions import HttpFileResponse, HttpResponse, HttpStreamResponse
from bustan.platform.http.compiler import DeclaredResponse, ResponsePlan, ResponseStrategy
from bustan.platform.http.responses import ResponseHandler


def test_serialized_responses_apply_response_plan_status_and_headers() -> None:
    response = ResponseHandler().write(
        result={"status": "ok"},
        response_plan=ResponsePlan(
            declared_type=dict,
            strategy=ResponseStrategy.STANDARD,
            default_status_code=201,
            declared_responses=(DeclaredResponse(status=201),),
            headers=(("x-response-plan", "enabled"),),
        ),
    )

    assert isinstance(response, HttpResponse)
    assert response.status_code == 201
    assert response.headers["x-response-plan"] == "enabled"
    assert response.body == b'{"status":"ok"}'


def test_raw_response_mode_bypasses_serialization() -> None:
    raw_response = HttpResponse(status_code=202, headers={"x-raw": "yes"}, body=b"raw")

    response = ResponseHandler().write(
        result=raw_response,
        response_plan=ResponsePlan(
            declared_type=HttpResponse,
            strategy=ResponseStrategy.RAW,
            default_status_code=200,
            declared_responses=(DeclaredResponse(status=200),),
        ),
    )

    assert response is raw_response
    assert response.status_code == 202
    assert response.body == b"raw"


def test_stream_and_file_responses_preserve_adapter_neutral_write_semantics(tmp_path: Path) -> None:
    file_path = tmp_path / "payload.txt"
    file_path.write_text("hello from file", encoding="utf-8")

    def payload_stream() -> Iterator[bytes]:
        yield b"hello"
        yield b" "
        yield b"stream"

    stream_response = ResponseHandler().write(
        result=payload_stream(),
        response_plan=ResponsePlan(
            declared_type=Iterator[bytes],
            strategy=ResponseStrategy.STREAM,
            default_status_code=200,
            declared_responses=(DeclaredResponse(status=200),),
        ),
    )
    file_response = ResponseHandler().write(
        result=file_path,
        response_plan=ResponsePlan(
            declared_type=Path,
            strategy=ResponseStrategy.FILE,
            default_status_code=200,
            declared_responses=(DeclaredResponse(status=200),),
        ),
    )

    assert isinstance(stream_response, HttpStreamResponse)
    assert b"".join(cast(Iterator[bytes], stream_response.body)) == b"hello stream"
    assert isinstance(file_response, HttpFileResponse)
    assert Path(file_response.path) == file_path


def test_response_handler_covers_passthrough_and_error_branches() -> None:
    native_response = Response(status_code=200, content=b"ok")
    raw_response = ResponseHandler().write(
        result=native_response,
        response_plan=ResponsePlan(
            declared_type=Response,
            strategy=ResponseStrategy.RAW,
            default_status_code=204,
            declared_responses=(DeclaredResponse(status=204),),
            headers=(("x-raw", "yes"),),
        ),
    )

    assert raw_response is native_response
    assert raw_response.status_code == 204
    assert raw_response.headers["x-raw"] == "yes"

    stream = HttpStreamResponse(body=iter((b"a", b"b")))
    file_response = HttpFileResponse(path="payload.txt")

    assert ResponseHandler().write(
        result=stream,
        response_plan=ResponsePlan(
            declared_type=Iterator[bytes],
            strategy=ResponseStrategy.STREAM,
            declared_responses=(DeclaredResponse(status=200),),
        ),
    ) is stream
    assert ResponseHandler().write(
        result=file_response,
        response_plan=ResponsePlan(
            declared_type=Path,
            strategy=ResponseStrategy.FILE,
            declared_responses=(DeclaredResponse(status=200),),
        ),
    ) is file_response

    with pytest.raises(TypeError, match="Unsupported raw response type"):
        ResponseHandler().write(
            result={"status": "ok"},
            response_plan=ResponsePlan(
                declared_type=HttpResponse,
                strategy=ResponseStrategy.RAW,
                declared_responses=(DeclaredResponse(status=200),),
            ),
        )

    with pytest.raises(TypeError, match="Unsupported stream response type"):
        ResponseHandler().write(
            result=b"not-a-stream",
            response_plan=ResponsePlan(
                declared_type=Iterator[bytes],
                strategy=ResponseStrategy.STREAM,
                declared_responses=(DeclaredResponse(status=200),),
            ),
        )

    with pytest.raises(TypeError, match="Unsupported file response type"):
        ResponseHandler().write(
            result=123,
            response_plan=ResponsePlan(
                declared_type=Path,
                strategy=ResponseStrategy.FILE,
                declared_responses=(DeclaredResponse(status=200),),
            ),
        )


def test_response_handler_uses_custom_serializer_for_standard_results() -> None:
    class CustomSerializer:
        def serialize(self, value: object) -> HttpResponse:
            return HttpResponse.json({"wrapped": value}, status_code=200)

    response = ResponseHandler(serializer=CustomSerializer()).write(
        result="value",
        response_plan=ResponsePlan(
            declared_type=str,
            strategy=ResponseStrategy.STANDARD,
            default_status_code=202,
            declared_responses=(DeclaredResponse(status=202),),
        ),
    )

    assert isinstance(response, HttpResponse)
    assert response.status_code == 202
    assert response.body == b'{"wrapped":"value"}'