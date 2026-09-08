"""The lock both resolution drivers take before building one shared instance.

A shared instance is built once and kept, so two callers that find its slot empty at
the same time must not both build it: one of the two is discarded with nothing to
close it. Serializing that only serializes anything if the driver that waits and the
driver that awaits queue on the same lock, which is what these tests hold in place.
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Any

import anyio
import pytest
from anyio import to_thread

from bustan.kernel.ioc.runtime import locks
from bustan.kernel.ioc.runtime.locks import shared_construction
from bustan.kernel.ioc.scopes import ScopeManager

if TYPE_CHECKING:
    from collections.abc import Callable


def test_an_awaited_caller_waits_for_the_thread_that_is_already_building() -> None:
    scopes = ScopeManager()
    order: list[str] = []

    def build_synchronously() -> None:
        with scopes.get_construction_lock("pool"):
            time.sleep(0.2)
            order.append("thread")

    async def scenario() -> None:
        thread = threading.Thread(target=build_synchronously)
        thread.start()
        await anyio.sleep(0.05)
        async with shared_construction(scopes, "pool"):
            order.append("loop")
        thread.join()

    anyio.run(scenario)

    assert order == ["thread", "loop"]
    # An entry lives only while somebody holds it or is queued behind it, so a lock
    # table that has emptied is the table saying both callers left.
    assert len(scopes.construction_locks) == 0


def test_a_wait_that_fails_after_the_lock_was_taken_gives_it_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Waiting for the other driver happens in a worker thread, and a backend may report
    # a cancelled wait either by failing the call the worker was made through or at the
    # next point the caller can be interrupted. The first of those leaves the worker
    # holding a lock its caller never sees, and this forces it: the worker takes the
    # lock and the call it was made through fails anyway.
    class AbandoningRunner:
        @staticmethod
        async def run_sync(function: Callable[..., Any], *arguments: Any) -> Any:
            await to_thread.run_sync(function, *arguments)
            raise RuntimeError("the wait was abandoned")

    monkeypatch.setattr(locks, "to_thread", AbandoningRunner)
    scopes = ScopeManager()

    def build_synchronously() -> None:
        with scopes.get_construction_lock("pool"):
            time.sleep(0.2)

    async def scenario() -> None:
        thread = threading.Thread(target=build_synchronously)
        thread.start()
        await anyio.sleep(0.05)
        with pytest.raises(RuntimeError):
            async with shared_construction(scopes, "pool"):
                pass
        thread.join()

        # A lock left held by the abandoned wait is a lock nobody can take again, so
        # this is the assertion: the deadline is what makes a leak a failure rather
        # than a suite that never finishes.
        with anyio.fail_after(5):
            async with shared_construction(scopes, "pool"):
                pass

    anyio.run(scenario)

    assert len(scopes.construction_locks) == 0
