"""A request-scoped controller over a three-deep request-scoped provider chain.

Nothing on this path is cached between requests, so what is timed is the cost of building
a fresh object graph for every caller.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from harness import RequestDriver
    from pytest_benchmark.fixture import BenchmarkFixture


def bench_request_scoped_chain(
    benchmark: BenchmarkFixture, request_scoped_driver: RequestDriver
) -> None:
    """Time one request that rebuilds its whole provider chain."""

    status = benchmark(request_scoped_driver.send_request)
    assert status == 200
