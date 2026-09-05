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

if TYPE_CHECKING:
    from .types import AsgiApp, Message, Scope

# What one connection may send before it is answered with a status instead of read
# further: a request line, then the whole header block.
MAX_REQUEST_LINE_BYTES = 8 * 1024
MAX_HEADER_BLOCK_BYTES = 64 * 1024


class HttpParseError(Exception):
    """Raised when a request cannot be read, carrying the status that answers it."""

    def __init__(self, status: int, reason: str) -> None:
        super().__init__(reason)
        self.status = status
        self.reason = reason


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
            await self._app(scope, _once(body), _writer_send(writer))
            await writer.drain()
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
    lookup = {name.lower(): value for name, value in headers}
    if b"transfer-encoding" in lookup:
        raise HttpParseError(HTTPStatus.NOT_IMPLEMENTED, "Transfer-Encoding is not supported")
    body = await _read_body(reader, lookup.get(b"content-length"), max_body_bytes)
    path, _, query = target.partition(b"?")
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": version.decode("latin-1").removeprefix("HTTP/"),
        "method": method.decode("latin-1"),
        "scheme": "http",
        "path": path.decode("latin-1"),
        "raw_path": path,
        "query_string": query,
        "root_path": "",
        "headers": headers,
        "client": writer.get_extra_info("peername"),
        "server": writer.get_extra_info("sockname"),
    }, body


def _parse_request_line(line: bytes) -> tuple[bytes, bytes, bytes]:
    parts = line.split()
    if len(parts) != 3 or not parts[2].startswith(b"HTTP/"):
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


def _once(body: bytes):
    """Return a receive callable yielding *body* once, then reporting a disconnect."""

    messages: list[Message] = [
        {"type": "http.request", "body": body, "more_body": False},
        {"type": "http.disconnect"},
    ]

    async def receive() -> Message:
        return messages.pop(0) if len(messages) > 1 else messages[0]

    return receive


def _writer_send(writer: asyncio.StreamWriter):
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
