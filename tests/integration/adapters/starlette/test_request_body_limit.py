"""What a body that declares no length costs the process before the limit refuses it.

Nothing here uses a test client. A client sends the body it is given and reports the
response; what this file is about is the other side of that exchange - how many bytes
the application asked the transport for before it answered - and only driving the ASGI
callable directly can count them. The receive callable each test builds is the meter:
it hands out one chunk at a time and records what it handed over.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, cast

import anyio

from bustan import Controller, Module, Post, create_app
from bustan.runtime.execution import set_request_limits
from bustan.runtime.params import RequestLimits

if TYPE_CHECKING:
    from bustan.app.application import Application

_LIMIT = 1024
_CHUNK = 64 * 1024
_OVER_THE_LIMIT = 20 * 1024 * 1024


@Controller("/notes")
class NotesController:
    """A route that binds the request body, so serving it means reading one."""

    @Post("/")
    def create(self, title: str) -> dict[str, str]:
        return {"title": title}


@Module(controllers=[NotesController])
class AppModule:
    pass


class _Exchange:
    """One request driven straight at the ASGI application, counting what it consumed."""

    def __init__(self, body: bytes, *, chunk_bytes: int) -> None:
        self._body = body
        self._chunk_bytes = chunk_bytes
        self._offset = 0
        self.consumed = 0
        self.messages: list[dict[str, Any]] = []

    async def receive(self) -> dict[str, Any]:
        chunk = self._body[self._offset : self._offset + self._chunk_bytes]
        self._offset += len(chunk)
        self.consumed += len(chunk)
        return {
            "type": "http.request",
            "body": chunk,
            "more_body": self._offset < len(self._body),
        }

    async def send(self, message: dict[str, Any]) -> None:
        self.messages.append(message)

    @property
    def status(self) -> int:
        return next(m["status"] for m in self.messages if m["type"] == "http.response.start")

    @property
    def payload(self) -> object:
        body = b"".join(
            m.get("body", b"") for m in self.messages if m["type"] == "http.response.body"
        )
        return json.loads(body)


def _application() -> Application:
    application = create_app(AppModule)
    set_request_limits(application, RequestLimits(max_body_bytes=_LIMIT))
    return application


def _post(application: Application, body: bytes, *, chunk_bytes: int = _CHUNK) -> _Exchange:
    """Send *body* with no declared length, one chunk at a time, and return the meter."""

    exchange = _Exchange(body, chunk_bytes=chunk_bytes)
    scope: dict[str, Any] = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "path": "/notes",
        "raw_path": b"/notes",
        "root_path": "",
        "scheme": "http",
        "query_string": b"",
        # No content-length: the length of this body is not knowable until it has
        # arrived, which is the whole point of the exchange.
        "headers": [
            (b"host", b"testserver"),
            (b"content-type", b"application/json"),
            (b"transfer-encoding", b"chunked"),
        ],
        "client": ("127.0.0.1", 50000),
        "server": ("testserver", 80),
    }

    async def drive() -> None:
        await cast(Any, application)(scope, exchange.receive, exchange.send)

    anyio.run(drive)
    return exchange


def test_an_undeclared_body_over_the_limit_is_refused_while_it_is_being_read() -> None:
    # The status alone proves nothing here: an oversized body was refused with 413
    # before this test existed, after the whole of it had been read into the process.
    # What the limit is for is the memory, so what is asserted is the memory: the
    # application stops asking for chunks once one crosses the limit, and never sees
    # the twenty megabytes behind it.
    exchange = _post(_application(), b"x" * _OVER_THE_LIMIT)

    assert exchange.status == 413
    assert exchange.consumed <= _LIMIT + _CHUNK
    assert exchange.consumed < _OVER_THE_LIMIT
    assert exchange.payload == {
        "type": "about:blank",
        "title": "Content Too Large",
        "status": 413,
        "detail": "The request body exceeds the 1024 byte limit",
        "instance": "/notes",
    }


def test_the_refusal_lands_on_the_chunk_that_crosses_the_limit() -> None:
    # Driven a byte at a time, the read stops on the first byte past the limit rather
    # than at some larger bound that happens to be smaller than the body.
    exchange = _post(_application(), b"x" * (_LIMIT * 4), chunk_bytes=1)

    assert exchange.status == 413
    assert exchange.consumed == _LIMIT + 1


def test_an_undeclared_body_within_the_limit_is_served_unchanged() -> None:
    body = b'{"title": "ada"}'

    exchange = _post(_application(), body, chunk_bytes=4)

    assert exchange.status == 200
    assert exchange.payload == {"title": "ada"}
    assert exchange.consumed == len(body)
