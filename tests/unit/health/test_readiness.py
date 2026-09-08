"""Unit tests for the two lifecycle edges readiness turns on."""

from __future__ import annotations

import pytest

from bustan import HealthStatus, ReadinessState
from bustan.health.readiness import LIFECYCLE_CHECK_NAME, LifecycleIndicator


def test_a_fresh_state_has_neither_started_nor_been_asked_to_stop() -> None:
    state = ReadinessState()

    assert state.started is False
    assert state.draining is False


def test_the_bootstrap_hook_is_what_records_that_startup_finished() -> None:
    state = ReadinessState()

    state.on_application_bootstrap()

    assert state.started is True
    assert state.draining is False


def test_draining_is_idempotent_and_is_never_reversed_by_a_later_start() -> None:
    state = ReadinessState()
    state.on_application_bootstrap()

    state.begin_drain()
    state.begin_drain()
    state.on_application_bootstrap()

    assert state.draining is True


def test_a_teardown_nobody_announced_still_takes_the_process_out_of_rotation() -> None:
    state = ReadinessState()
    state.on_application_bootstrap()

    state.before_application_shutdown(None)

    assert state.draining is True


def test_the_state_carries_no_attribute_a_caller_can_add_to_it() -> None:
    state = ReadinessState()

    with pytest.raises(AttributeError):
        state.ready = True  # ty: ignore[unresolved-attribute]


@pytest.mark.anyio
async def test_the_lifecycle_check_reports_down_until_startup_finishes() -> None:
    state = ReadinessState()
    indicator = LifecycleIndicator(state)

    assert indicator.name == LIFECYCLE_CHECK_NAME
    before = await indicator.check()
    state.on_application_bootstrap()
    after = await indicator.check()

    assert before.status is HealthStatus.DOWN
    assert before.detail == "startup has not completed"
    assert after.status is HealthStatus.UP
    assert after.detail is None


@pytest.mark.anyio
async def test_the_lifecycle_check_reports_draining_ahead_of_a_startup_that_never_finished() -> (
    None
):
    state = ReadinessState()
    state.begin_drain()

    result = await LifecycleIndicator(state).check()

    assert result.status is HealthStatus.DOWN
    assert result.detail == "the process is draining"


@pytest.mark.anyio
async def test_the_lifecycle_check_reports_down_once_a_started_process_drains() -> None:
    state = ReadinessState()
    state.on_application_bootstrap()
    indicator = LifecycleIndicator(state)

    serving = await indicator.check()
    state.begin_drain()
    draining = await indicator.check()

    assert serving.status is HealthStatus.UP
    assert draining.status is HealthStatus.DOWN
    assert draining.detail == "the process is draining"
