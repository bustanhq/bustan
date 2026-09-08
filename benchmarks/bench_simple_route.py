"""One GET route on a default-scoped controller: routing, injection, binding, response."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from harness import RequestDriver
    from pytest_benchmark.fixture import BenchmarkFixture


def bench_simple_route(benchmark: BenchmarkFixture, simple_route_driver: RequestDriver) -> None:
    """Time one request to a route with nothing on it but the framework itself."""

    status = benchmark(simple_route_driver.send_request)
    assert status == 200
