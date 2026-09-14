"""One GET answered with a hundred items, so the cost of a larger body is on the path.

The items are built once, so what grows over the simple route is serializing and sending a
body a hundred items long rather than the handler building one. It is timed and printed, and
the gate does not judge it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from harness import RequestDriver
    from pytest_benchmark.fixture import BenchmarkFixture


def bench_hundred_items_route(
    benchmark: BenchmarkFixture, hundred_items_route_driver: RequestDriver
) -> None:
    """Time one request answered with a JSON list of a hundred items."""

    status = benchmark(hundred_items_route_driver.send_request)
    assert status == 200
