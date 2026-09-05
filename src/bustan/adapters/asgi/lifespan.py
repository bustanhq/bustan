"""Driving an application's lifespan from the side a server is normally on.

The ASGI lifespan protocol is a conversation: the server sends ``lifespan.startup``, the
application answers when it has started, and the same happens again for shutdown. A test
client has to hold up the server's end of that conversation, which is what this does.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from .types import AsgiApp, Message

# What the application is told about the server holding the other end of the protocol.
_LIFESPAN_SCOPE: dict[str, object] = {
    "type": "lifespan",
    "asgi": {"version": "3.0", "spec_version": "2.3"},
    "state": {},
}


class LifespanFailed(RuntimeError):
    """Raised when an application reported that startup or shutdown failed."""


class LifespanRunner:
    """Holds the server's end of one application's lifespan conversation."""

    def __init__(self, app: AsgiApp) -> None:
        self._app = app
        self._to_app: asyncio.Queue[Message] = asyncio.Queue()
        self._from_app: asyncio.Queue[Message] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None

    async def startup(self) -> None:
        """Start the application and wait for it to report that it has started."""

        task = asyncio.create_task(self._run())
        self._task = task
        try:
            await self._exchange("lifespan.startup")
        except BaseException:
            # A startup that failed ends the conversation, so the application is left
            # holding a lifespan connection nobody will speak on again.
            self._task = None
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            raise

    async def shutdown(self) -> None:
        """Stop the application and wait for its lifespan to finish."""

        if self._task is None:
            return
        await self._exchange("lifespan.shutdown")
        await self._task
        self._task = None

    async def _run(self) -> None:
        """Call the application with a lifespan connection and hold it open."""

        await self._app(dict(_LIFESPAN_SCOPE), self._to_app.get, self._from_app.put)

    async def _exchange(self, request: str) -> None:
        """Send one lifespan message and raise whatever failure the answer reports."""

        await self._to_app.put({"type": request})
        answer = await self._await_answer()
        if answer["type"].endswith(".failed"):
            raise LifespanFailed(cast(str, answer.get("message", "")) or answer["type"])

    async def _await_answer(self) -> Message:
        """Return the application's next lifespan message, or what killed it trying.

        An application whose lifespan raised never sends anything, so waiting only on the
        answer would wait forever; the task is awaited alongside it so the original
        exception is what surfaces.
        """

        task = cast("asyncio.Task[None]", self._task)
        answer = asyncio.ensure_future(self._from_app.get())
        done, _pending = await asyncio.wait({answer, task}, return_when=asyncio.FIRST_COMPLETED)
        if answer in done:
            return answer.result()
        answer.cancel()
        task.result()
        raise LifespanFailed("The application ended its lifespan without answering")


__all__ = (
    "LifespanFailed",
    "LifespanRunner",
)
