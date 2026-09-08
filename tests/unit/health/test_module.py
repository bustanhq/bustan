"""Unit tests for the health module wired into a real application."""

from __future__ import annotations

from typing import Any, cast

import pytest

from bustan import (
    HealthIndicatorResult,
    HealthModule,
    HealthReport,
    HealthService,
    HealthStatus,
    Injectable,
    Module,
    ReadinessState,
    ThrottlerModule,
    create_app,
    create_app_context,
)
from bustan.health.controller import HEALTHY_STATUS_CODE, UNHEALTHY_STATUS_CODE
from bustan.testing import AsgiTestClient

from .conftest import CallbackIndicator, HangingIndicator, StubIndicator


@Module(imports=(HealthModule.for_root(),))
class HealthOnlyModule:
    pass


@pytest.mark.anyio
async def test_readiness_is_false_before_startup_and_true_after_it_completes() -> None:
    context = create_app_context(HealthOnlyModule)
    # One service, read on both sides of startup, so the two answers are the same
    # object changing its mind rather than two objects that were never comparable.
    service = context.get(HealthService)

    before = await service.readiness()
    await context.init()
    after = await service.readiness()

    assert before.as_dict() == {
        "status": "down",
        "checks": {"lifecycle": {"status": "down", "detail": "startup has not completed"}},
    }
    assert after.as_dict() == {
        "status": "up",
        "checks": {"lifecycle": {"status": "up", "detail": None}},
    }

    await context.close()


@pytest.mark.anyio
async def test_a_hook_that_runs_during_startup_sees_readiness_still_false() -> None:
    observed: list[HealthReport] = []

    @Injectable
    class SlowDependency:
        def __init__(self, health: HealthService) -> None:
            self._health = health

        async def on_module_init(self) -> None:
            observed.append(await self._health.readiness())

    @Module(imports=(HealthModule.for_root(),), providers=(SlowDependency,))
    class RootModule:
        pass

    context = create_app_context(RootModule)
    await context.init()

    # Module initialization is a startup stage, so readiness was still false there, and
    # it is true only once every stage has run.
    assert [report.status for report in observed] == [HealthStatus.DOWN]
    assert observed[0].checks["lifecycle"].detail == "startup has not completed"
    assert (await context.get(HealthService).readiness()).status is HealthStatus.UP

    await context.close()


@pytest.mark.anyio
async def test_an_indicator_registered_during_startup_gates_readiness_from_the_start() -> None:
    warm = False

    @Injectable
    class Cache:
        def __init__(self, health: HealthService) -> None:
            health.register_readiness(
                CallbackIndicator(
                    "cache",
                    lambda: (
                        HealthIndicatorResult.up()
                        if warm
                        else HealthIndicatorResult.down("still filling")
                    ),
                )
            )

    @Module(imports=(HealthModule.for_root(),), providers=(Cache,))
    class RootModule:
        pass

    context = create_app_context(RootModule)
    await context.init()
    service = context.get(HealthService)

    cold = await service.readiness()
    warm = True
    filled = await service.readiness()

    assert cold.status is HealthStatus.DOWN
    assert cold.checks["cache"].detail == "still filling"
    assert filled.status is HealthStatus.UP

    await context.close()


@pytest.mark.anyio
async def test_a_started_application_that_is_asked_to_stop_reports_unready() -> None:
    context = create_app_context(HealthOnlyModule)
    await context.init()
    service = context.get(HealthService)

    serving = await service.readiness()
    context.get(ReadinessState).begin_drain()
    draining = await service.readiness()
    alive = await service.liveness()

    assert serving.status is HealthStatus.UP
    assert draining.status is HealthStatus.DOWN
    assert draining.checks["lifecycle"].detail == "the process is draining"
    # Draining is not a reason to restart the process, only to stop routing to it.
    assert alive.status is HealthStatus.UP

    await context.close()


@pytest.mark.anyio
async def test_teardown_takes_the_process_out_of_rotation_even_when_nothing_announced_it() -> None:
    context = create_app_context(HealthOnlyModule)
    await context.init()
    state = context.get(ReadinessState)

    await context.close()

    assert state.draining is True


@pytest.mark.anyio
async def test_a_restarted_application_starts_out_unready_again() -> None:
    context = create_app_context(HealthOnlyModule)
    await context.init()
    first = context.get(ReadinessState)
    await context.close()

    await context.init()
    second = context.get(ReadinessState)

    assert first is not second
    assert second.draining is False
    assert second.started is True

    await context.close()


def test_the_probe_routes_answer_over_http_with_the_status_a_reader_acts_on() -> None:
    application = create_app(HealthOnlyModule)

    with AsgiTestClient(cast(Any, application)) as client:
        live = client.get("/health/live")
        ready = client.get("/health/ready")
        application.get(ReadinessState).begin_drain()
        drained = client.get("/health/ready")

    assert live.status_code == HEALTHY_STATUS_CODE
    assert live.json() == {"status": "up", "checks": {}}
    assert ready.status_code == HEALTHY_STATUS_CODE
    assert ready.json() == {
        "status": "up",
        "checks": {"lifecycle": {"status": "up", "detail": None}},
    }
    assert drained.status_code == UNHEALTHY_STATUS_CODE
    assert drained.json() == {
        "status": "down",
        "checks": {"lifecycle": {"status": "down", "detail": "the process is draining"}},
    }
    assert drained.headers["cache-control"] == "no-store"


def test_a_failing_dependency_takes_the_readiness_route_down_and_leaves_liveness_up() -> None:
    @Injectable
    class Database:
        def __init__(self, health: HealthService) -> None:
            health.register_readiness(
                StubIndicator("database", HealthIndicatorResult.down("no route to host"))
            )

    @Module(imports=(HealthModule.for_root(),), providers=(Database,))
    class RootModule:
        pass

    with AsgiTestClient(cast(Any, create_app(RootModule))) as client:
        live = client.get("/health/live")
        ready = client.get("/health/ready")

    assert live.status_code == HEALTHY_STATUS_CODE
    assert ready.status_code == UNHEALTHY_STATUS_CODE
    assert ready.json()["checks"]["database"] == {
        "status": "down",
        "detail": "no route to host",
    }


def test_the_module_exports_what_a_shutdown_sequence_and_an_indicator_owner_need() -> None:
    application = create_app(HealthOnlyModule)

    assert isinstance(application.get(ReadinessState), ReadinessState)
    assert isinstance(application.get(HealthService), HealthService)


@pytest.mark.anyio
async def test_the_check_timeout_the_module_is_given_bounds_a_check_that_hangs() -> None:
    @Injectable
    class Stuck:
        def __init__(self, health: HealthService) -> None:
            health.register_readiness(HangingIndicator("database"))

    @Module(imports=(HealthModule.for_root(check_timeout=0.01),), providers=(Stuck,))
    class RootModule:
        pass

    context = create_app_context(RootModule)
    await context.init()

    report = await context.get(HealthService).readiness()

    assert report.checks["database"].detail == "the check did not answer in time"

    await context.close()


def test_the_probe_routes_are_not_counted_against_a_throttled_caller() -> None:
    @Module(
        imports=(HealthModule.for_root(), ThrottlerModule.for_root(ttl=60, limit=1)),
    )
    class RootModule:
        pass

    with AsgiTestClient(cast(Any, create_app(RootModule))) as client:
        answers = [client.get("/health/ready").status_code for _ in range(4)]

    # A probe read on an interval would exhaust a limit meant for ordinary traffic
    # within the first window, and the process would then be reported failed for load
    # that was never its own.
    assert answers == [HEALTHY_STATUS_CODE] * 4
