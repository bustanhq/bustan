"""What this transport writes, and the conversion from the framework's responses into it."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, cast

import pytest

from bustan.adapters.asgi.responses import (
    AsgiFileResponse,
    AsgiResponse,
    AsgiResponseValue,
    AsgiStreamResponse,
    plain_text,
    to_asgi_response,
)
from bustan.contracts import HttpFileResponse, HttpResponse, HttpStreamResponse

if TYPE_CHECKING:
    from pathlib import Path

    from bustan.adapters.asgi.types import Message


async def _write(response: AsgiResponseValue) -> list[Message]:
    messages: list[Message] = []

    async def send(message: Message) -> None:
        messages.append(message)

    await response(send)
    return messages


def _headers(messages: list[Message]) -> dict[str, str]:
    start = messages[0]
    return {name.decode(): value.decode() for name, value in start["headers"]}


def _body(messages: list[Message]) -> bytes:
    return b"".join(message.get("body", b"") for message in messages[1:])


@pytest.mark.anyio
async def test_a_response_writes_a_start_message_and_one_body_message() -> None:
    messages = await _write(AsgiResponse(status_code=201, body=b"created"))

    assert messages[0]["type"] == "http.response.start"
    assert messages[0]["status"] == 201
    assert _body(messages) == b"created"
    assert messages[-1]["more_body"] is False


@pytest.mark.anyio
async def test_a_textual_response_declares_the_charset_it_was_encoded_in() -> None:
    messages = await _write(AsgiResponse(body=b"hello", media_type="text/plain"))

    assert _headers(messages)["content-type"] == "text/plain; charset=utf-8"


@pytest.mark.anyio
async def test_a_content_type_the_caller_set_is_left_alone() -> None:
    messages = await _write(
        AsgiResponse(body=b"hello", headers={"Content-Type": "text/csv"}, media_type="text/plain")
    )

    assert _headers(messages)["content-type"] == "text/csv"


@pytest.mark.anyio
async def test_a_response_declares_the_length_of_the_body_it_wrote() -> None:
    messages = await _write(AsgiResponse(body=b"hello"))

    assert _headers(messages)["content-length"] == "5"


@pytest.mark.anyio
async def test_a_status_that_carries_no_body_declares_neither_a_body_nor_a_length() -> None:
    messages = await _write(AsgiResponse(status_code=204, body=b"ignored"))

    assert "content-length" not in _headers(messages)
    assert _body(messages) == b""


@pytest.mark.anyio
async def test_a_stream_response_writes_one_message_per_chunk() -> None:
    messages = await _write(AsgiStreamResponse(body=[b"hello", b" ", b"stream"]))

    assert _body(messages) == b"hello stream"
    assert "content-length" not in _headers(messages)
    assert messages[-1]["more_body"] is False


@pytest.mark.anyio
async def test_a_stream_response_reads_an_asynchronous_source_too() -> None:
    async def chunks() -> AsyncIterator[bytes]:
        yield b"hello"
        yield b" async"

    messages = await _write(AsgiStreamResponse(body=chunks()))

    assert _body(messages) == b"hello async"


@pytest.mark.anyio
async def test_a_stream_response_encodes_text_chunks_as_utf_8() -> None:
    messages = await _write(AsgiStreamResponse(body=cast("list[bytes]", ["héllo"])))

    assert _body(messages) == "héllo".encode()


@pytest.mark.anyio
async def test_a_file_response_writes_the_file_with_its_length_and_guessed_type(
    tmp_path: Path,
) -> None:
    path = tmp_path / "greeting.txt"
    path.write_text("hello file", encoding="utf-8")

    messages = await _write(AsgiFileResponse(path=path))

    assert _body(messages) == b"hello file"
    assert _headers(messages)["content-length"] == "10"
    assert _headers(messages)["content-type"] == "text/plain; charset=utf-8"


@pytest.mark.anyio
async def test_a_file_response_naming_a_download_says_so_in_both_header_forms(
    tmp_path: Path,
) -> None:
    path = tmp_path / "report.bin"
    path.write_bytes(b"\x00\x01")

    messages = await _write(AsgiFileResponse(path=path, filename="rapport final.txt"))

    disposition = _headers(messages)["content-disposition"]
    assert 'filename="rapport final.txt"' in disposition
    assert "filename*=utf-8''rapport%20final.txt" in disposition


@pytest.mark.anyio
async def test_a_file_of_an_unrecognised_kind_is_served_as_opaque_bytes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "archive.unknownext"
    path.write_bytes(b"\x00")

    messages = await _write(AsgiFileResponse(path=path))
    declared = await _write(AsgiFileResponse(path=path, media_type="application/zip"))

    assert _headers(messages)["content-type"] == "application/octet-stream"
    assert _headers(declared)["content-type"] == "application/zip"


@pytest.mark.anyio
async def test_a_file_response_reads_a_file_larger_than_one_chunk(tmp_path: Path) -> None:
    path = tmp_path / "large.bin"
    path.write_bytes(b"x" * (128 * 1024 + 7))

    messages = await _write(AsgiFileResponse(path=path))

    assert len(_body(messages)) == 128 * 1024 + 7
    assert len([message for message in messages if message["type"] == "http.response.body"]) > 2


@pytest.mark.anyio
async def test_a_missing_file_fails_before_a_status_claims_the_response_succeeded(
    tmp_path: Path,
) -> None:
    with pytest.raises(FileNotFoundError):
        await _write(AsgiFileResponse(path=tmp_path / "absent.txt"))


def test_each_neutral_response_converts_into_the_response_that_writes_it() -> None:
    converted = to_asgi_response(HttpResponse.json({"ok": True}, status_code=201))

    assert isinstance(converted, AsgiResponse)
    assert converted.status_code == 201
    assert converted.body == b'{"ok":true}'
    assert converted.media_type == "application/json"


def test_a_neutral_stream_response_converts_into_a_stream_response() -> None:
    converted = to_asgi_response(HttpStreamResponse(body=[b"a"], media_type="text/plain"))

    assert isinstance(converted, AsgiStreamResponse)
    assert converted.media_type == "text/plain"


def test_a_neutral_file_response_converts_into_a_file_response() -> None:
    converted = to_asgi_response(HttpFileResponse(path="/tmp/x", filename="x.txt"))

    assert isinstance(converted, AsgiFileResponse)
    assert converted.filename == "x.txt"


def test_a_response_this_transport_already_built_is_passed_through() -> None:
    response = AsgiResponse(body=b"kept")

    assert to_asgi_response(response) is response


def test_anything_this_transport_cannot_write_is_refused_by_name() -> None:
    with pytest.raises(TypeError, match="Cannot write int as an ASGI response"):
        to_asgi_response(7)


def test_the_transports_own_answer_is_plain_text_with_the_headers_it_was_given() -> None:
    response = plain_text("Not Found", status_code=404, allow="GET")

    assert response.status_code == 404
    assert response.body == b"Not Found"
    assert response.headers == {"allow": "GET"}
