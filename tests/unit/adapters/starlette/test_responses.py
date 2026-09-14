"""Conversion of the framework's neutral responses into Starlette's own."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, cast

import pytest
from starlette.responses import FileResponse, Response, StreamingResponse
from starlette.types import Message, Scope, Send

from bustan.adapters.starlette import to_starlette_response
from bustan.adapters.starlette.responses import write_response
from bustan.contracts import HttpFileResponse, HttpResponse, HttpStreamResponse

_SCOPE: Scope = {"type": "http", "method": "GET", "path": "/", "headers": []}


async def _receive() -> Message:
    return {"type": "http.request", "body": b"", "more_body": False}


async def _sent(write: Callable[[Send], Awaitable[None]]) -> list[Message]:
    """Run *write* against a server that keeps every message it is sent."""

    sent: list[Message] = []

    async def send(message: Message) -> None:
        sent.append(message)

    await write(send)
    return sent


@pytest.mark.anyio
@pytest.mark.parametrize(
    "response",
    [
        pytest.param(
            HttpResponse.json({"status": "ok"}, status_code=201, headers={"X-Trace": "abc"}),
            id="json-with-a-capitalised-header",
        ),
        pytest.param(
            HttpResponse(body=b"plain", media_type="text/plain"), id="text-naming-no-charset"
        ),
        pytest.param(
            HttpResponse(body=b"<p>", media_type="text/html; Charset=ISO-8859-1"),
            id="text-naming-its-charset",
        ),
        pytest.param(
            HttpResponse(
                body=b"{}",
                headers={"Content-Type": "application/problem+json"},
                media_type="application/json",
            ),
            id="content-type-set-by-the-handler",
        ),
        pytest.param(
            HttpResponse(body=b"sized", headers={"Content-Length": "5"}),
            id="length-set-by-the-handler",
        ),
        pytest.param(HttpResponse(body=b"bare"), id="no-media-type"),
        pytest.param(HttpResponse.empty(), id="no-content"),
        pytest.param(HttpResponse(status_code=304), id="not-modified"),
        pytest.param(HttpResponse(status_code=103), id="informational"),
        pytest.param(
            HttpResponse(body=cast(Any, "still text"), media_type="text/plain"),
            id="body-still-text",
        ),
        pytest.param(
            Response(content=b"native", status_code=202, headers={"x-native": "yes"}),
            id="built-in-starlettes-terms",
        ),
    ],
)
async def test_a_response_is_written_exactly_as_starlettes_own_response_writes_it(
    response: object,
) -> None:
    """The messages match Starlette's response message for message, headers in order.

    A plain response is written without a Starlette response being built, so its headers
    are rendered by the adapter rather than by Starlette. Comparing against Starlette's
    own response is what holds that rendering to Starlette's rules, in every case where
    they differ, and in any Starlette release that changes them.
    """

    written = await _sent(lambda send: write_response(response, _SCOPE, _receive, send))
    expected = await _sent(lambda send: to_starlette_response(response)(_SCOPE, _receive, send))

    assert written == expected


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
