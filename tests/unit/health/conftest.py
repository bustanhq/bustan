"""Indicators the health tests register, kept in one place so no test grows its own."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import cast

from bustan import HealthIndicatorResult
from bustan.observability import Logger


class StubIndicator:
    """An indicator that answers with whatever the test handed it."""

    def __init__(self, name: str, result: HealthIndicatorResult) -> None:
        self._name = name
        self._result = result
        self.calls = 0

    @property
    def name(self) -> str:
        return self._name

    async def check(self) -> HealthIndicatorResult:
        self.calls += 1
        return self._result


class RaisingIndicator:
    """An indicator whose check fails the way a broken dependency check does."""

    def __init__(self, name: str, failure: Exception) -> None:
        self._name = name
        self._failure = failure

    @property
    def name(self) -> str:
        return self._name

    async def check(self) -> HealthIndicatorResult:
        raise self._failure


class HangingIndicator:
    """An indicator that never answers, which is the other way a check fails."""

    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    async def check(self) -> HealthIndicatorResult:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


class LyingIndicator:
    """An indicator that answers with something that is not a result."""

    def __init__(self, name: str, answer: object) -> None:
        self._name = name
        self._answer = answer

    @property
    def name(self) -> str:
        return self._name

    async def check(self) -> HealthIndicatorResult:
        return cast(HealthIndicatorResult, self._answer)


class CallbackIndicator:
    """An indicator that answers from a callable the test can change between probes."""

    def __init__(self, name: str, answer: Callable[[], HealthIndicatorResult]) -> None:
        self._name = name
        self._answer = answer

    @property
    def name(self) -> str:
        return self._name

    async def check(self) -> HealthIndicatorResult:
        return self._answer()


class RecordingLogger(Logger):
    """A logger that keeps what it was told instead of writing it.

    A test that provokes a failing indicator provokes an error log with it, and the run
    should neither print it nor lose it: the message is the only place the detail a
    probe response deliberately withholds is still recorded.
    """

    def __init__(self) -> None:
        super().__init__("HealthTest")
        self.errors: list[str] = []

    def error(self, message: str, trace: str | None = None, context: str | None = None) -> None:
        self.errors.append(message)


class RendezvousIndicator:
    """An indicator that answers only once another indicator has also started.

    Two of these can only both answer if the probe checks them at the same time, which
    is what makes the concurrency of a probe testable without measuring a clock.
    """

    def __init__(self, name: str, arrived: asyncio.Event, waits_for: asyncio.Event) -> None:
        self._name = name
        self._arrived = arrived
        self._waits_for = waits_for

    @property
    def name(self) -> str:
        return self._name

    async def check(self) -> HealthIndicatorResult:
        self._arrived.set()
        await self._waits_for.wait()
        return HealthIndicatorResult.up()
