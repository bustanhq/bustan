"""The simple route with a synchronous handler, and nothing else about it changed.

The two applications differ in ``def`` against ``async def`` and in nothing else, so the gap
between this measurement and the simple one is what handing the handler to a worker thread
costs. It is timed and printed, and the gate does not judge it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from harness import RequestDriver
    from pytest_benchmark.fixture import BenchmarkFixture


def bench_sync_route(benchmark: BenchmarkFixture, sync_route_driver: RequestDriver) -> None:
    """Time one request whose handler runs on a worker thread."""

    status = benchmark(sync_route_driver.send_request)
    assert status == 200
