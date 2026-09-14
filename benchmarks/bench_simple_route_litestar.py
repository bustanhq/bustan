"""Litestar serving the request ``bench_simple_route`` times, through the same driver.

Printed beside the gate as the multiple Bustan's median is of this one, and never judged.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from harness import RequestDriver
    from pytest_benchmark.fixture import BenchmarkFixture


def bench_simple_route_litestar(
    benchmark: BenchmarkFixture, simple_route_litestar_driver: RequestDriver
) -> None:
    """Time Litestar answering the simple route."""

    status = benchmark(simple_route_litestar_driver.send_request)
    assert status == 200
