"""Fixtures shared by the benchmark modules.

Each driver is built once per benchmark and torn down after it, so application assembly -
module graph, container, route compilation - is outside every measurement. What is timed
is the steady state a served application is in, which is the state a regression would show
up in.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from typing import Any

import pytest
from applications import (
    ITEM_PATH,
    PipelineModule,
    RequestScopedModule,
    ResolutionModule,
    SimpleModule,
)
from calibration import CalibrationDriver
from harness import RequestDriver, build_application

from bustan.app.application import Application


@pytest.fixture
def calibration_driver() -> Iterator[CalibrationDriver]:
    with CalibrationDriver() as driver:
        yield driver


@pytest.fixture
def simple_route_driver() -> Iterator[RequestDriver]:
    with RequestDriver(SimpleModule, ITEM_PATH) as driver:
        yield driver


@pytest.fixture
def pipeline_route_driver() -> Iterator[RequestDriver]:
    with RequestDriver(PipelineModule, ITEM_PATH) as driver:
        yield driver


@pytest.fixture
def request_scoped_driver() -> Iterator[RequestDriver]:
    with RequestDriver(RequestScopedModule, ITEM_PATH) as driver:
        yield driver


@pytest.fixture
def resolution_application() -> Iterator[Application]:
    application, _ = build_application(ResolutionModule)
    asyncio.run(application.init())
    try:
        yield application
    finally:
        asyncio.run(application.close())


def pytest_benchmark_update_machine_info(
    config: pytest.Config, machine_info: dict[str, Any]
) -> None:
    """Record the hash seed alongside the machine, because the numbers depend on it.

    Dictionary layout follows the hash seed and the framework's hot path is dictionaries,
    so a run under a different seed is a run against a different memory layout. The gate
    reads this field back and says so when a result and the baseline disagree.
    """

    machine_info["python_hash_seed"] = os.environ.get("PYTHONHASHSEED", "random")
