"""A small HTTP/1.1 server, so that an application on this adapter can actually run.

Every other adapter borrows a server from the library it binds. This one has no library,
so it speaks the subset of HTTP/1.1 an ASGI application needs and refuses the rest: one
request per connection, a body delimited by ``Content-Length``, and a response delimited
by closing the connection. That is enough to serve an application locally and to prove
the adapter end to end; a deployment puts a real server in front of it.

Anything the parser does not recognise is answered with a status rather than guessed at,
because a request smuggled past a lenient parser is a request nobody audited.
"""

from __future__ import annotations

import asyncio
from http import HTTPStatus
from typing import TYPE_CHECKING, cast

from .lifespan import LifespanRunner
from .requests import DEFAULT_MAX_BODY_BYTES

# The error every refusal on this path raises is defined beside the target parser, which
# raises it too, and is re-exported here because this is the module that answers it.
from .targets import HttpParseError, parse_request_target

if TYPE_CHECKING:
    from .types import AsgiApp, Message, Scope

# What one connection may send before it is answered with a status instead of read
# further: a request line, then the whole header block.
MAX_REQUEST_LINE_BYTES = 8 * 1024
MAX_HEADER_BLOCK_BYTES = 64 * 1024

# How much is taken from a connection at a time while waiting for the client to leave.
# One request is answered per connection and the whole of it has already been read, so
# whatever this collects is discarded; only the end of the stream is being waited for.
_TRAILING_READ_BYTES = 4096


class AsgiServer:
    """Serves one ASGI application over TCP until it is asked to stop."""

    def __init__(
        self,
        app: AsgiApp,
        *,
        host: str = "127.0.0.1",
        port: int = 8000,
        max_body_bytes: int | None = DEFAULT_MAX_BODY_BYTES,
    ) -> None:
        self._app = app
        self._host = host
        self._port = port
        self._max_body_bytes = max_body_bytes
        self._server: asyncio.Server | None = None
        self._stopped = asyncio.Event()

    async def serve(self) -> None:
        """Run the application's lifespan around serving, until :meth:`stop` is called."""

        lifespan = LifespanRunner(self._app)
        await lifespan.startup()
        self._server = await asyncio.start_server(
            self._handle, self._host, self._port, limit=MAX_HEADER_BLOCK_BYTES
        )
        try:
            async with self._server:
                await self._stopped.wait()
        finally:
            self._server = None
            self._stopped.clear()
            await lifespan.shutdown()

    async def stop(self) -> None:
        """Ask the running server to stop; doing so when none runs does nothing."""

        self._stopped.set()

    @property
    def sockets(self) -> tuple[object, ...]:
        """The sockets the server is listening on, empty until it is serving."""

        return () if self._server is None else tuple(self._server.sockets)

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            try:
                scope, body = await _read_request(reader, writer, self._max_body_bytes)
            except HttpParseError as error:
                _write_status(writer, error.status, error.reason)
                return
            channel = _ConnectionChannel(body)
            watching = asyncio.create_task(_watch_for_the_peer_leaving(reader, channel))
            try:
                await self._app(scope, channel.receive, _writer_send(writer, channel))
                await writer.drain()
            finally:
                watching.cancel()
                await asyncio.gather(watching, return_exceptions=True)
        except (ConnectionError, asyncio.IncompleteReadError):
            # The client went away mid-exchange; there is nobody left to answer.
            pass
        finally:
            writer.close()


async def _read_request(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    max_body_bytes: int | None,
) -> tuple[Scope, bytes]:
    """Read one request into the scope an ASGI application is called with."""

    method, target, version = _parse_request_line(await _read_line(reader))
    headers = await _read_headers(reader)
    if any(name == b"transfer-encoding" for name, _value in headers):
        raise HttpParseError(HTTPStatus.NOT_IMPLEMENTED, "Transfer-Encoding is not supported")
    body = await _read_body(reader, _content_length(headers), max_body_bytes)
    parsed = parse_request_target(target)
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": version.decode("ascii").removeprefix("HTTP/"),
        "method": method.decode("ascii"),
        "scheme": "http",
        "path": parsed.path,
        "raw_path": parsed.raw_path,
        "query_string": parsed.query_string,
        "root_path": "",
        "headers": headers,
        "client": writer.get_extra_info("peername"),
        "server": writer.get_extra_info("sockname"),
    }, body


def _parse_request_line(line: bytes) -> tuple[bytes, bytes, bytes]:
    """Split one request line into its method, target and version.

    A request line is ASCII, so a byte outside it is refused here rather than decoded
    into whichever character the byte happens to stand for in some other encoding: a
    method or a version read that way is a request nobody sent. The target is held to
    the same rule again where it is parsed, because the parser is also called by a client
    that never saw a request line.
    """

    parts = line.split()
    if len(parts) != 3 or not parts[2].startswith(b"HTTP/") or not line.isascii():
        raise HttpParseError(HTTPStatus.BAD_REQUEST, "Malformed request line")
    return parts[0], parts[1], parts[2]


async def _read_line(reader: asyncio.StreamReader) -> bytes:
    try:
        line = await reader.readuntil(b"\r\n")
    except (asyncio.LimitOverrunError, ValueError) as error:
        raise HttpParseError(
            HTTPStatus.REQUEST_HEADER_FIELDS_TOO_LARGE, "Header block too large"
        ) from error
    if len(line) > MAX_REQUEST_LINE_BYTES:
        raise HttpParseError(HTTPStatus.REQUEST_URI_TOO_LONG, "Request line too long")
    return line.rstrip(b"\r\n")


async def _read_headers(reader: asyncio.StreamReader) -> list[tuple[bytes, bytes]]:
    headers: list[tuple[bytes, bytes]] = []
    read = 0
    while True:
        line = await _read_line(reader)
        if not line:
            return headers
        read += len(line)
        if read > MAX_HEADER_BLOCK_BYTES:
            raise HttpParseError(
                HTTPStatus.REQUEST_HEADER_FIELDS_TOO_LARGE, "Header block too large"
            )
        name, separator, value = line.partition(b":")
        if not separator:
            raise HttpParseError(HTTPStatus.BAD_REQUEST, "Malformed header line")
        headers.append((name.strip().lower(), value.strip()))


def _content_length(headers: list[tuple[bytes, bytes]]) -> bytes | None:
    """Return the one body length the request declared, refusing a disagreement.

    Two ``Content-Length`` fields that disagree leave the length of the body ambiguous,
    and a server that picks one of them can be made to disagree with a proxy in front of
    it that picked the other. There is no safe choice between them, so the request is
    refused rather than answered. Repeats that agree say one thing twice and are read as
    the one thing they say.
    """

    declared = {value for name, value in headers if name == b"content-length"}
    if not declared:
        return None
    if len(declared) > 1:
        raise HttpParseError(HTTPStatus.BAD_REQUEST, "Conflicting Content-Length headers")
    return declared.pop()


async def _read_body(
    reader: asyncio.StreamReader, content_length: bytes | None, max_body_bytes: int | None
) -> bytes:
    if content_length is None:
        return b""
    if not content_length.isdigit():
        raise HttpParseError(HTTPStatus.BAD_REQUEST, "Malformed Content-Length")
    length = int(content_length)
    if max_body_bytes is not None and length > max_body_bytes:
        raise HttpParseError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Request body too large")
    return await reader.readexactly(length)


class _ConnectionChannel:
    """The receive side of one connection, held open until something really ends it.

    An application that watches for a disconnect while it writes stops writing when it
    sees one, so a disconnect reported before the client sent it costs the client the
    rest of the response: the status arrives with a truncated or empty body behind it
    and nothing is raised. The disconnect therefore belongs to the events that cause it,
    of which this connection has two, and it is reported at whichever happens first.

    The first is the client leaving, seen as its end of the connection reaching end of
    file or failing outright. That is the truth about the connection rather than an
    inference from the response, and it is what lets an application that streams until
    its client hangs up be told that the client hung up.

    The second is the response being finished, because one request is answered per
    connection and the connection is closed once the last body message has been written:
    there is no client on it after that either. Without it an application that asks for
    the next message after finishing its response would wait for a client that is still
    there and has nothing left to say, and the connection would never be closed.

    Waiting is the point rather than a delay to be tuned away, so nothing here expires.
    An application streaming to a client that is still connected is doing what it was
    asked to; a deadline would end that exchange on the clock rather than on the client.
    """

    __slots__ = ("_body", "_body_taken", "_ended")

    def __init__(self, body: bytes) -> None:
        self._body = body
        self._body_taken = False
        self._ended = asyncio.Event()

    async def receive(self) -> Message:
        """Yield the request body once, then the disconnect whatever ended the exchange."""

        if not self._body_taken:
            self._body_taken = True
            return {"type": "http.request", "body": self._body, "more_body": False}
        await self._ended.wait()
        return {"type": "http.disconnect"}

    def note_sent(self, message: Message) -> None:
        """Record one message written back, to know when the response is finished."""

        if message.get("type") == "http.response.body" and not message.get("more_body", False):
            self._ended.set()

    def note_peer_gone(self) -> None:
        """Record that the client's end of the connection has gone."""

        self._ended.set()


async def _watch_for_the_peer_leaving(
    reader: asyncio.StreamReader, channel: _ConnectionChannel
) -> None:
    """Tell *channel* when the client's end of the connection has gone.

    The request has been read in full and no second one is answered on this connection,
    so anything that still arrives is discarded and only the end of the stream matters.
    A connection that was reset rather than closed raises instead of ending, and says
    the same thing.

    A client that shuts down only its sending direction and stays to read its response
    arrives here as the same end of stream and is read as gone, because the two cannot
    be told apart on a socket this server will not read again. The alternative is to
    wait for a write to fail, which reports the client leaving only after a response has
    been produced for nobody, and reports nothing at all to an application that stopped
    writing to wait for the next message.
    """

    try:
        while await reader.read(_TRAILING_READ_BYTES):
            pass
    except OSError:
        pass
    channel.note_peer_gone()


def _writer_send(writer: asyncio.StreamWriter, channel: _ConnectionChannel):
    """Return a send callable that writes ASGI response messages as HTTP/1.1 bytes.

    The connection is closed once the last body message has been written, which is what
    tells the client where a response with no declared length ended.
    """

    async def send(message: Message) -> None:
        if message.get("type") == "http.response.start":
            status = cast(int, message["status"])
            headers = cast("list[tuple[bytes, bytes]]", message.get("headers", []))
            writer.write(_status_line(status))
            for name, value in [*headers, (b"connection", b"close")]:
                writer.write(name + b": " + value + b"\r\n")
            writer.write(b"\r\n")
        elif message.get("type") == "http.response.body":
            writer.write(cast(bytes, message.get("body", b"")))
            await writer.drain()
        channel.note_sent(message)

    return send


def _status_line(status: int) -> bytes:
    try:
        reason = HTTPStatus(status).phrase
    except ValueError:
        reason = ""
    return f"HTTP/1.1 {status} {reason}\r\n".encode("latin-1")


def _write_status(writer: asyncio.StreamWriter, status: int, reason: str) -> None:
    body = reason.encode("utf-8")
    writer.write(_status_line(status))
    writer.write(b"content-type: text/plain; charset=utf-8\r\n")
    writer.write(b"content-length: " + str(len(body)).encode("latin-1") + b"\r\n")
    writer.write(b"connection: close\r\n\r\n")
    writer.write(body)


__all__ = (
    "MAX_HEADER_BLOCK_BYTES",
    "MAX_REQUEST_LINE_BYTES",
    "AsgiServer",
    "HttpParseError",
)
