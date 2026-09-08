"""Unit tests for aggregation, and for every way one indicator can fail a probe."""

from __future__ import annotations

import asyncio

import pytest

from bustan import HealthIndicatorResult, HealthService, HealthStatus, ReadinessState
from bustan.health.service import DEFAULT_CHECK_TIMEOUT

from .conftest import (
    CallbackIndicator,
    HangingIndicator,
    LyingIndicator,
    RaisingIndicator,
    RecordingLogger,
    RendezvousIndicator,
    StubIndicator,
)


def _started_service(
    *,
    check_timeout: float = DEFAULT_CHECK_TIMEOUT,
    logger: RecordingLogger | None = None,
) -> HealthService:
    """Build a service over an application that has finished starting up."""

    state = ReadinessState()
    state.on_application_bootstrap()
    return HealthService(
        state,
        check_timeout=check_timeout,
        logger=logger if logger is not None else RecordingLogger(),
    )


def test_a_probe_is_refused_a_timeout_that_could_never_expire() -> None:
    for timeout in (0.0, -1.0):
        with pytest.raises(ValueError, match="positive number of seconds"):
            HealthService(ReadinessState(), check_timeout=timeout)


@pytest.mark.anyio
async def test_liveness_answers_up_without_consulting_the_lifecycle() -> None:
    service = HealthService(ReadinessState())

    report = await service.liveness()

    assert report.as_dict() == {"status": "up", "checks": {}}


@pytest.mark.anyio
async def test_liveness_stays_up_while_readiness_reports_a_draining_process() -> None:
    state = ReadinessState()
    state.on_application_bootstrap()
    service = HealthService(state)
    state.begin_drain()

    assert (await service.liveness()).status is HealthStatus.UP
    assert (await service.readiness()).status is HealthStatus.DOWN


@pytest.mark.anyio
async def test_readiness_begins_with_the_lifecycle_check_and_liveness_does_not() -> None:
    service = _started_service()

    assert tuple((await service.readiness()).checks) == ("lifecycle",)
    assert tuple((await service.liveness()).checks) == ()


@pytest.mark.anyio
async def test_an_indicator_on_one_probe_is_not_consulted_by_the_other() -> None:
    service = _started_service()
    live = StubIndicator("deadlock", HealthIndicatorResult.up())
    ready = StubIndicator("database", HealthIndicatorResult.up())
    service.register_liveness(live)
    service.register_readiness(ready)

    await service.liveness()

    assert (live.calls, ready.calls) == (1, 0)


@pytest.mark.anyio
async def test_one_down_indicator_takes_the_whole_probe_down() -> None:
    service = _started_service()
    service.register_readiness(StubIndicator("queue", HealthIndicatorResult.up()))
    service.register_readiness(StubIndicator("database", HealthIndicatorResult.down("no route")))

    report = await service.readiness()

    assert report.as_dict() == {
        "status": "down",
        "checks": {
            "lifecycle": {"status": "up", "detail": None},
            "queue": {"status": "up", "detail": None},
            "database": {"status": "down", "detail": "no route"},
        },
    }


@pytest.mark.anyio
async def test_an_indicator_that_raises_reports_unhealthy_instead_of_failing_the_probe() -> None:
    logger = RecordingLogger()
    service = _started_service(logger=logger)
    service.register_readiness(RaisingIndicator("database", RuntimeError("dsn=user:pw@host")))
    service.register_readiness(StubIndicator("queue", HealthIndicatorResult.up()))

    report = await service.readiness()

    assert report.status is HealthStatus.DOWN
    assert report.checks["database"] == HealthIndicatorResult.down("the check failed")
    # Every other indicator is still consulted, and nothing the exception carried
    # reaches a caller that can read the probe. The log keeps what the probe withheld.
    assert report.checks["queue"].status is HealthStatus.UP
    assert "pw@host" not in repr(report.as_dict())
    assert logger.errors == ["Health indicator 'database' raised RuntimeError: dsn=user:pw@host"]


@pytest.mark.anyio
async def test_an_indicator_that_never_answers_is_recorded_down_rather_than_hanging() -> None:
    service = _started_service(check_timeout=0.01)
    service.register_readiness(HangingIndicator("database"))
    service.register_readiness(StubIndicator("queue", HealthIndicatorResult.up()))

    report = await service.readiness()

    assert report.status is HealthStatus.DOWN
    assert report.checks["database"].detail == "the check did not answer in time"
    assert report.checks["queue"].status is HealthStatus.UP


@pytest.mark.anyio
async def test_an_indicator_that_answers_with_something_unusable_is_recorded_down() -> None:
    service = _started_service()
    service.register_readiness(LyingIndicator("database", {"status": "up"}))

    report = await service.readiness()

    assert report.checks["database"] == HealthIndicatorResult.down(
        "the check answered with an unusable result"
    )


@pytest.mark.anyio
async def test_a_recovered_indicator_is_reported_up_on_the_next_probe() -> None:
    service = _started_service()
    answers = iter((HealthIndicatorResult.down("cold"), HealthIndicatorResult.up()))
    service.register_readiness(CallbackIndicator("cache", lambda: next(answers)))

    first = await service.readiness()
    second = await service.readiness()

    assert first.status is HealthStatus.DOWN
    assert second.status is HealthStatus.UP


def test_two_indicators_cannot_share_one_name_on_the_same_probe() -> None:
    service = _started_service()
    service.register_readiness(StubIndicator("database", HealthIndicatorResult.up()))

    with pytest.raises(ValueError, match="already registered"):
        service.register_readiness(StubIndicator("database", HealthIndicatorResult.up()))


def test_the_lifecycle_check_name_is_reserved_on_the_readiness_probe() -> None:
    service = _started_service()

    with pytest.raises(ValueError, match="already registered"):
        service.register_readiness(StubIndicator("lifecycle", HealthIndicatorResult.up()))


def test_the_same_name_may_be_used_once_on_each_probe() -> None:
    service = _started_service()

    service.register_liveness(StubIndicator("database", HealthIndicatorResult.up()))
    service.register_readiness(StubIndicator("database", HealthIndicatorResult.up()))


@pytest.mark.anyio
async def test_the_indicators_of_one_probe_are_checked_at_the_same_time() -> None:
    service = _started_service(check_timeout=0.5)
    first, second = asyncio.Event(), asyncio.Event()
    service.register_readiness(RendezvousIndicator("queue", first, second))
    service.register_readiness(RendezvousIndicator("database", second, first))

    report = await service.readiness()

    # Checked one after another, neither could answer: the first would wait for a check
    # that had not started, and the timeout would report both down.
    assert report.status is HealthStatus.UP
