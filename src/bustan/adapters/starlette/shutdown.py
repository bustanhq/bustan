"""Draining a running server: what it counts, what it refuses, and when it is idle.

A deployment replaces one process with another while callers are mid-request. What
decides whether those callers see an answer or a reset is whether the process on its
way out finishes the requests it already accepted before it tears its application
down, and whether it stops accepting new ones while it does. Both are decisions about
requests rather than about sockets, so they are made here, in front of the
application, rather than left to whatever the server library does with a signal.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..asgi.types import AsgiApp, Message, Receive, Scope, Send

# What a caller is told when it arrives after the server has decided to stop. The shape
# is the framework's own error contract, written out here because the pipeline that
# would build it needs an execution context and a container, and a request refused at
# the door has neither.
_DRAINING_PROBLEM: dict[str, object] = {
    "type": "about:blank",
    "title": "Service Unavailable",
    "status": 503,
    "detail": "The server is shutting down and is not accepting new requests.",
}
_DRAINING_BODY = json.dumps(_DRAINING_PROBLEM, separators=(",", ":")).encode("utf-8")
_PROBLEM_MEDIA_TYPE = b"application/problem+json"


class DrainGate:
    """Counts the requests a server is serving and refuses new ones once it is draining.

    Draining runs one way. A server that has begun to drain is on its way down, and the
    gate never reopens, so no request admitted after that decision can outlive the
    teardown that follows it. A gate belongs to one run of one server; starting a
    server again builds a new one.
    """

    __slots__ = ("_draining", "_idle", "_in_flight")

    def __init__(self) -> None:
        self._in_flight = 0
        self._draining = False
        self._idle = asyncio.Event()
        self._idle.set()

    @property
    def draining(self) -> bool:
        """Whether the gate has been closed against new requests."""

        return self._draining

    @property
    def in_flight(self) -> int:
        """How many requests the server is serving at this moment."""

        return self._in_flight

    def begin_drain(self) -> None:
        """Refuse every request from here on; the ones already in flight run on."""

        self._draining = True

    def admit(self) -> bool:
        """Record one more request in flight, or report that the gate is closed."""

        if self._draining:
            return False
        self._in_flight += 1
        self._idle.clear()
        return True

    def release(self) -> None:
        """Record that one request the gate admitted has finished."""

        self._in_flight -= 1
        if self._in_flight <= 0:
            self._idle.set()

    async def wait_until_idle(self, timeout: float | None) -> bool:
        """Wait up to ``timeout`` seconds for every request in flight to finish.

        The answer says whether they all did. A false answer is the caller's cue to
        carry on shutting down regardless: one request that never returns must not be
        able to hold a process open for as long as it likes, because the deployment
        replacing that process is already waiting on it.
        """

        if self._in_flight <= 0:
            return True
        if timeout is not None and timeout <= 0:
            return False
        try:
            await asyncio.wait_for(self._idle.wait(), timeout)
        except TimeoutError:
            return False
        return True


class DrainingApp:
    """Wrap an ASGI application so its server can count and then stop its requests.

    Only HTTP connections are counted and refused. Everything else the server opens,
    the lifespan among it, is passed through untouched: the lifespan is how the server
    tells the application to shut down, so a gate that closed against it would be
    closing against the very message it exists to make safe.
    """

    __slots__ = ("_app", "_gate")

    def __init__(self, app: AsgiApp, gate: DrainGate) -> None:
        self._app = app
        self._gate = gate

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Serve one connection, unless the gate has closed against new requests."""

        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return
        if not self._gate.admit():
            await _refuse(send)
            return
        try:
            await self._app(scope, receive, send)
        finally:
            self._gate.release()


async def _refuse(send: Send) -> None:
    """Answer one request the server will not serve, and close the connection.

    The connection is closed with the answer so that a caller holding the socket open
    does not send its next request into a server that is halfway through going away.
    """

    start: Message = {
        "type": "http.response.start",
        "status": 503,
        "headers": [
            (b"content-type", _PROBLEM_MEDIA_TYPE),
            (b"content-length", str(len(_DRAINING_BODY)).encode("latin-1")),
            (b"connection", b"close"),
        ],
    }
    await send(start)
    body: Message = {"type": "http.response.body", "body": _DRAINING_BODY}
    await send(body)


__all__ = ("DrainGate", "DrainingApp")
