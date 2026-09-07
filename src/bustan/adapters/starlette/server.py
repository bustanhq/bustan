"""The Uvicorn server this adapter runs, and where a stop signal is seen.

Uvicorn installs the process signal handlers for as long as it serves and restores
them when it stops, so a handler installed around serving is replaced for exactly the
window in which a signal matters. That makes the server object, not the caller that
started it, the only place a stop signal can be observed reliably, which is why the
framework's shutdown sequence is attached here rather than wrapped around ``serve``.
"""

from __future__ import annotations

import signal
import socket
from collections.abc import Awaitable, Callable
from types import FrameType

import uvicorn

from .shutdown import DrainGate

# What the shutdown sequence is given: the name of the signal that asked the process to
# stop, or nothing when a caller asked instead.
type ShutdownSequence = Callable[[str | None], Awaitable[None]]


class GracefulServer(uvicorn.Server):
    """A Uvicorn server that drains and tears the application down before it exits.

    The base server answers a signal by leaving its accept loop and then closing what
    it holds. Two things are added around that. The signal is named, so the teardown
    hooks can be told which one arrived. And the framework's own sequence runs first,
    while the listening socket is still open, so that a caller arriving during the
    drain is answered rather than met with a closed port, and a load balancer polling
    this process sees it refuse before it disappears.
    """

    def __init__(
        self, config: uvicorn.Config, gate: DrainGate, shut_down: ShutdownSequence
    ) -> None:
        super().__init__(config)
        self._gate = gate
        self._shut_down = shut_down
        self._signal_name: str | None = None

    def handle_exit(self, sig: int, frame: FrameType | None) -> None:
        """Record which signal asked the process to stop, then stop accepting.

        The gate closes here rather than when the shutdown sequence reaches it, because
        the moment the signal arrives is the moment this process stops being a place to
        send a request. Waiting for the server to notice would admit callers into a
        process that has already been told to go.

        Only the first signal is recorded. A second is an operator asking the same
        server to hurry up, and the teardown is already being told why it is running.
        """

        if self._signal_name is None:
            self._signal_name = signal.Signals(sig).name
        self._gate.begin_drain()
        super().handle_exit(sig, frame)

    async def shutdown(self, sockets: list[socket.socket] | None = None) -> None:
        """Run the framework's shutdown sequence, then let Uvicorn release the socket."""

        await self._shut_down(self._signal_name)
        await super().shutdown(sockets)


__all__ = ("GracefulServer", "ShutdownSequence")
