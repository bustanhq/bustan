"""Conversion of the framework's neutral responses into Starlette's own."""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.responses import FileResponse, Response, StreamingResponse

from bustan.adapters.starlette import to_starlette_response
from bustan.contracts import HttpFileResponse, HttpResponse, HttpStreamResponse


def test_a_neutral_response_becomes_a_starlette_response() -> None:
    response = HttpResponse.json({"status": "ok"}, status_code=201)
    response.headers["x-test"] = "present"

    adapted = to_starlette_response(response)

    assert isinstance(adapted, Response)
    assert adapted.status_code == 201
    assert adapted.headers["x-test"] == "present"
    assert adapted.body == b'{"status":"ok"}'


def test_a_transport_built_response_is_passed_through_unchanged() -> None:
    response = Response(content=b"native", status_code=202)

    assert to_starlette_response(response) is response


def test_a_stream_response_becomes_a_starlette_streaming_response() -> None:
    adapted = to_starlette_response(
        HttpStreamResponse(body=[b"one", b"two"], media_type="text/plain")
    )

    assert isinstance(adapted, StreamingResponse)
    assert adapted.media_type == "text/plain"


def test_a_file_response_becomes_a_starlette_file_response(tmp_path: Path) -> None:
    served = tmp_path / "report.txt"
    served.write_text("hello")

    adapted = to_starlette_response(HttpFileResponse(path=served, filename="report.txt"))

    assert isinstance(adapted, FileResponse)


def test_something_that_is_not_a_response_is_refused() -> None:
    with pytest.raises(TypeError, match="Cannot write"):
        to_starlette_response(object())
