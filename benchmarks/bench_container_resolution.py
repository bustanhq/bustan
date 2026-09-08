"""Container resolution on its own, with no request and no HTTP anywhere near it."""

from __future__ import annotations

from typing import TYPE_CHECKING

from applications import ReportBuilder, ResolutionModule

if TYPE_CHECKING:
    from pytest_benchmark.fixture import BenchmarkFixture

    from bustan.app.application import Application


def bench_container_resolution(
    benchmark: BenchmarkFixture, resolution_application: Application
) -> None:
    """Time resolving a transient provider whose dependencies are already built."""

    container = resolution_application.container
    resolved = benchmark(container.resolve, ReportBuilder, module=ResolutionModule)
    assert isinstance(resolved, ReportBuilder)
