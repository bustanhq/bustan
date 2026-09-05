"""The small HTTP/1.1 server that lets an application on this adapter actually run."""

from __future__ import annotations

import asyncio

import pytest

from bustan.adapters.asgi.application import AsgiApplication
from bustan.adapters.asgi.requests import DEFAULT_MAX_BODY_BYTES
from bustan.adapters.asgi.server import AsgiServer
from bustan.contracts import AdapterRoute, HttpRequest, HttpResponse, HttpStreamResponse


async def _echo(request: HttpRequest) -> HttpResponse:
    return HttpResponse.json(
        {
            "method": request.method,
            "path": request.path,
            "query": request.query_params.getlist("page"),
            "body": (await request.body()).decode(),
        }
    )


async def _stream(_request: HttpRequest) -> HttpStreamResponse:
    return HttpStreamResponse(body=[b"hello", b" stream"])


async def _odd(_request: HttpRequest) -> HttpResponse:
    return HttpResponse(status_code=599, body=b"odd")


def _application() -> AsgiApplication:
    application = AsgiApplication()
    application.register(
        [
            AdapterRoute(path="/echo", methods=("GET", "POST"), handler=_echo),
            AdapterRoute(path="/stream", methods=("GET",), handler=_stream),
            AdapterRoute(path="/odd", methods=("GET",), handler=_odd),
        ]
    )
    return application


class _RunningServer:
    """A server listening on a port the operating system chose."""

    def __init__(self, server: AsgiServer, task: asyncio.Task[None], port: int) -> None:
        self.server, self.task, self.port = server, task, port


async def _start(max_body_bytes: int | None = DEFAULT_MAX_BODY_BYTES) -> _RunningServer:
    server = AsgiServer(_application(), host="127.0.0.1", port=0, max_body_bytes=max_body_bytes)
    task = asyncio.create_task(server.serve())
    while not server.sockets:
        await asyncio.sleep(0)
    port = server.sockets[0].getsockname()[1]  # ty: ignore[unresolved-attribute]
    return _RunningServer(server, task, port)


async def _stop(running: _RunningServer) -> None:
    await running.server.stop()
    await running.task


async def _speak(port: int, request: bytes) -> bytes:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(request)
    await writer.drain()
    answer = await reader.read()
    writer.close()
    return answer


@pytest.mark.anyio
async def test_a_request_over_a_socket_reaches_the_handler_and_comes_back() -> None:
    running = await _start()

    answer = await _speak(running.port, b"GET /echo?page=2 HTTP/1.1\r\nhost: localhost\r\n\r\n")
    await _stop(running)

    assert answer.startswith(b"HTTP/1.1 200 OK\r\n")
    assert b'"path":"/echo"' in answer
    assert b'"query":["2"]' in answer


@pytest.mark.anyio
async def test_a_request_body_is_read_up_to_the_length_it_declared() -> None:
    running = await _start()

    answer = await _speak(
        running.port,
        b"POST /echo HTTP/1.1\r\nhost: localhost\r\ncontent-length: 4\r\n\r\nbody",
    )
    await _stop(running)

    assert b'"body":"body"' in answer


@pytest.mark.anyio
async def test_a_streamed_response_is_delimited_by_closing_the_connection() -> None:
    running = await _start()

    answer = await _speak(running.port, b"GET /stream HTTP/1.1\r\nhost: localhost\r\n\r\n")
    await _stop(running)

    assert answer.endswith(b"hello stream")
    assert b"connection: close" in answer


@pytest.mark.anyio
async def test_a_malformed_request_line_is_answered_rather_than_guessed_at() -> None:
    running = await _start()

    answer = await _speak(running.port, b"GET\r\n\r\n")
    await _stop(running)

    assert answer.startswith(b"HTTP/1.1 400 Bad Request\r\n")
    assert answer.endswith(b"Malformed request line")


@pytest.mark.anyio
async def test_a_malformed_header_line_is_answered_rather_than_guessed_at() -> None:
    running = await _start()

    answer = await _speak(running.port, b"GET /echo HTTP/1.1\r\nnot-a-header\r\n\r\n")
    await _stop(running)

    assert answer.startswith(b"HTTP/1.1 400 Bad Request\r\n")


@pytest.mark.anyio
async def test_a_chunked_body_is_refused_rather_than_half_understood() -> None:
    running = await _start()

    answer = await _speak(
        running.port,
        b"POST /echo HTTP/1.1\r\nhost: localhost\r\ntransfer-encoding: chunked\r\n\r\n",
    )
    await _stop(running)

    assert answer.startswith(b"HTTP/1.1 501 Not Implemented\r\n")


@pytest.mark.anyio
async def test_a_content_length_that_is_not_a_number_is_refused() -> None:
    running = await _start()

    answer = await _speak(
        running.port, b"POST /echo HTTP/1.1\r\nhost: localhost\r\ncontent-length: many\r\n\r\n"
    )
    await _stop(running)

    assert answer.startswith(b"HTTP/1.1 400 Bad Request\r\n")


@pytest.mark.anyio
async def test_two_content_lengths_that_disagree_are_refused_rather_than_answered() -> None:
    running = await _start()

    answer = await _speak(
        running.port,
        b"POST /echo HTTP/1.1\r\nhost: localhost\r\n"
        b"content-length: 4\r\ncontent-length: 8\r\n\r\nabcdefgh",
    )
    await _stop(running)

    assert answer.startswith(b"HTTP/1.1 400 Bad Request\r\n")
    assert answer.endswith(b"Conflicting Content-Length headers")


@pytest.mark.anyio
async def test_two_content_lengths_that_agree_say_one_thing_twice() -> None:
    running = await _start()

    answer = await _speak(
        running.port,
        b"POST /echo HTTP/1.1\r\nhost: localhost\r\n"
        b"content-length: 4\r\ncontent-length: 4\r\n\r\nbody",
    )
    await _stop(running)

    assert answer.startswith(b"HTTP/1.1 200 OK\r\n")
    assert b'"body":"body"' in answer


@pytest.mark.anyio
async def test_a_body_beyond_the_limit_is_refused_before_it_is_read() -> None:
    running = await _start(max_body_bytes=8)

    answer = await _speak(
        running.port, b"POST /echo HTTP/1.1\r\nhost: localhost\r\ncontent-length: 64\r\n\r\n"
    )
    await _stop(running)

    assert answer.startswith(b"HTTP/1.1 413 ")


@pytest.mark.anyio
async def test_a_header_block_beyond_the_limit_is_refused_before_it_is_read() -> None:
    running = await _start()

    answer = await _speak(
        running.port,
        b"GET /echo HTTP/1.1\r\nhost: localhost\r\nx-big: " + b"x" * 70_000 + b"\r\n\r\n",
    )
    await _stop(running)

    assert answer.startswith(b"HTTP/1.1 431 ")


@pytest.mark.anyio
async def test_a_client_that_vanishes_before_sending_anything_is_not_an_error() -> None:
    running = await _start()

    _reader, writer = await asyncio.open_connection("127.0.0.1", running.port)
    writer.close()
    await asyncio.sleep(0)
    await _stop(running)

    assert running.task.done()


@pytest.mark.anyio
async def test_a_request_line_beyond_the_limit_is_refused_before_it_is_read() -> None:
    running = await _start()

    answer = await _speak(
        running.port, b"GET /echo?q=" + b"x" * 9_000 + b" HTTP/1.1\r\nhost: localhost\r\n\r\n"
    )
    await _stop(running)

    assert answer.startswith(b"HTTP/1.1 414 ")


@pytest.mark.anyio
async def test_many_small_headers_that_add_up_beyond_the_limit_are_refused() -> None:
    running = await _start()
    headers = b"".join(b"x-tag-%d: %s\r\n" % (index, b"y" * 900) for index in range(80))

    answer = await _speak(running.port, b"GET /echo HTTP/1.1\r\n" + headers + b"\r\n")
    await _stop(running)

    assert answer.startswith(b"HTTP/1.1 431 ")


@pytest.mark.anyio
async def test_a_status_with_no_standard_reason_is_still_written_as_a_status_line() -> None:
    running = await _start()

    answer = await _speak(running.port, b"GET /odd HTTP/1.1\r\nhost: localhost\r\n\r\n")
    await _stop(running)

    assert answer.startswith(b"HTTP/1.1 599 \r\n")


@pytest.mark.anyio
async def test_a_server_that_is_not_running_reports_no_sockets() -> None:
    assert AsgiServer(_application()).sockets == ()
