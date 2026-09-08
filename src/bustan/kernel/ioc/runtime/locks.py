"""One construction lock per shared instance, held the same way by both drivers.

A shared instance is built once and kept for every later caller, so two callers that
find the cache empty at the same time must not both build it: the loser's instance is
discarded with no teardown, and whatever it opened leaks. Serializing that is what a
construction lock is for, and it only serializes anything if both drivers take the
same lock.

The lock is a thread lock, because that is the only kind every caller can hold. A
synchronous resolution runs on whichever thread called it; an awaited one runs on an
event loop, and there may be several event loops in one process. A lock belonging to
one loop cannot be taken by a thread outside it, so it cannot serialize against one.

What an awaited caller must not do is stall its loop while it waits. So it queues on
the awaited lock first, which keeps two tasks on one loop from each occupying a worker
thread, and then takes the thread lock without blocking. Only a caller that finds the
thread lock held pays for a worker thread, and it pays for it where waiting costs the
loop nothing.
"""

from __future__ import annotations

import threading
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from anyio import to_thread

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from ..scopes import ScopeManager

__all__ = ["shared_construction"]


@asynccontextmanager
async def shared_construction(scopes: ScopeManager, key: object) -> AsyncIterator[None]:
    """Hold the lock an awaited construction shares with a synchronous one."""

    async with scopes.get_async_construction_lock(key):
        entry = scopes.construction_locks.borrow(key)
        try:
            if not entry.lock.acquire(blocking=False):
                await _acquired_off_the_loop(entry.lock)
            try:
                yield
            finally:
                entry.lock.release()
        finally:
            scopes.construction_locks.release(key, entry)


async def _acquired_off_the_loop(lock: threading.Lock) -> None:
    """Wait for a held thread lock in a worker thread, leaving the loop free to run.

    A cancellation is delivered only once the worker has finished, by which time the
    worker may already hold the lock. ``taken`` says whether it does, so a caller that
    is cancelled while waiting gives the lock back instead of leaving it held by a
    resolution that no longer exists.
    """

    taken: list[bool] = []

    def acquire() -> None:
        lock.acquire()
        taken.append(True)

    try:
        await to_thread.run_sync(acquire)
    except BaseException:
        if taken:
            lock.release()
        raise
