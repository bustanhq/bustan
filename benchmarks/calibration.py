"""A workload with no bustan in it, used to divide out how fast the machine is.

A benchmark number means nothing without the machine it was taken on, and a shared CI
runner is not one machine: the same job lands on hardware whose speed differs from run to
run by more than any regression worth catching. Every gated measurement is therefore
reported as a multiple of this workload, measured in the same process on the same runner,
so that the machine cancels and what is left is the framework.

That only works while this workload speeds up and slows down by the same factor the
request path does, which constrains what it is allowed to be. The request path is
interpreted bytecode: coroutines created and awaited, small calls, attribute reads on
slotted objects, dict construction and lookup, isinstance checks, string formatting. Time
spent inside a C extension does not scale with those, so there is deliberately almost
none here - one serialization per run rather than one per iteration. A normalizer with a
different instruction mix from the thing it normalizes tracks it only by accident, and on
a different machine it stops tracking it at all.
"""

from __future__ import annotations

import asyncio
import json

# Chosen so that one run of the workload costs roughly what one simple request costs.
# Sizing the normalizer like the thing it normalizes keeps the same relative resolution
# on both sides of the division, so the ratio is no noisier than its worse half.
ITERATIONS = 540


class _Item:
    __slots__ = ("item_id", "name")

    def __init__(self, item_id: int) -> None:
        self.item_id = item_id
        self.name = f"item-{item_id}"

    def as_payload(self) -> dict[str, object]:
        return {"item_id": self.item_id, "name": self.name, "in_stock": True}


async def _bind(index: int) -> dict[str, object]:
    payload = _Item(index).as_payload()
    payload["path"] = f"/items/{index}"
    return payload


async def _serve(index: int) -> int:
    payload = await _bind(index)
    measured = 0
    for key, value in payload.items():
        if isinstance(value, str):
            measured += len(key) + len(value)
        elif isinstance(value, bool):
            measured += 1
        else:
            measured += 2
    return measured


async def _workload() -> int:
    await asyncio.sleep(0)
    total = 0
    for index in range(ITERATIONS):
        total += await _serve(index)
    body = json.dumps({"total": total}, separators=(",", ":")).encode("utf-8")
    await asyncio.sleep(0)
    return len(body) + total


class CalibrationDriver:
    """Runs the workload through the same event-loop shell a request is driven through.

    Held to the same shape as ``RequestDriver`` on purpose: the loop hand-off that
    ``run_until_complete`` costs is then on both sides of the division and cancels with
    everything else about the machine.
    """

    __slots__ = ("_loop",)

    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()

    def __enter__(self) -> CalibrationDriver:
        return self

    def __exit__(self, *exception: object) -> None:
        self._loop.close()

    def run(self) -> int:
        """Run the workload once and return the byte count it produced."""

        return self._loop.run_until_complete(_workload())
