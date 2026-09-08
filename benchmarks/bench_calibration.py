"""The machine normalizer, which every other benchmark is reported as a multiple of."""

from __future__ import annotations

from typing import TYPE_CHECKING

from calibration import ITERATIONS

if TYPE_CHECKING:
    from calibration import CalibrationDriver
    from pytest_benchmark.fixture import BenchmarkFixture


def bench_calibration(benchmark: BenchmarkFixture, calibration_driver: CalibrationDriver) -> None:
    """Time a fixed workload that touches no framework code."""

    produced = benchmark(calibration_driver.run)
    assert produced > ITERATIONS
