"""The same route as the simple one, with a guard, a pipe and an interceptor on it.

The two applications differ in nothing else, so the gap between this measurement and the
simple one is what the pipeline costs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from harness import RequestDriver
    from pytest_benchmark.fixture import BenchmarkFixture


def bench_pipeline_route(benchmark: BenchmarkFixture, pipeline_route_driver: RequestDriver) -> None:
    """Time one request through a guard, a parameter pipe and an interceptor."""

    status = benchmark(pipeline_route_driver.send_request)
    assert status == 200
