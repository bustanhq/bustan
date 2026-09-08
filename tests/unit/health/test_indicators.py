"""Unit tests for the health value types and the response shape they render."""

from __future__ import annotations

import json
from types import MappingProxyType

import pytest

from bustan import HealthIndicatorResult, HealthReport, HealthStatus


def test_the_status_vocabulary_is_exactly_up_and_down() -> None:
    assert tuple(HealthStatus) == (HealthStatus.UP, HealthStatus.DOWN)
    assert HealthStatus.UP.value == "up"
    assert HealthStatus.DOWN.value == "down"


def test_a_serving_result_needs_no_detail_and_a_failing_one_carries_its_reason() -> None:
    assert HealthIndicatorResult.up() == HealthIndicatorResult(HealthStatus.UP, None)
    assert HealthIndicatorResult.up("warm") == HealthIndicatorResult(HealthStatus.UP, "warm")
    assert HealthIndicatorResult.down("no connection") == HealthIndicatorResult(
        HealthStatus.DOWN, "no connection"
    )


def test_a_result_cannot_be_edited_after_the_check_that_produced_it() -> None:
    result = HealthIndicatorResult.up()

    with pytest.raises(AttributeError):
        result.status = HealthStatus.DOWN  # ty: ignore[invalid-assignment]


def test_the_response_shape_is_two_levels_deep_with_every_key_always_present() -> None:
    report = HealthReport(
        status=HealthStatus.DOWN,
        checks=MappingProxyType(
            {
                "lifecycle": HealthIndicatorResult.down("startup has not completed"),
                "database": HealthIndicatorResult.up(),
            }
        ),
    )

    assert report.as_dict() == {
        "status": "down",
        "checks": {
            "lifecycle": {"status": "down", "detail": "startup has not completed"},
            "database": {"status": "up", "detail": None},
        },
    }


def test_the_response_shape_serialises_to_json_with_no_python_specific_values() -> None:
    report = HealthReport(
        status=HealthStatus.UP,
        checks=MappingProxyType({"database": HealthIndicatorResult.up()}),
    )

    assert json.loads(json.dumps(report.as_dict())) == {
        "status": "up",
        "checks": {"database": {"status": "up", "detail": None}},
    }


def test_an_empty_report_renders_an_empty_check_map_rather_than_omitting_the_key() -> None:
    report = HealthReport(status=HealthStatus.UP, checks=MappingProxyType({}))

    assert report.as_dict() == {"status": "up", "checks": {}}


def test_the_report_keeps_the_order_its_checks_were_registered_in() -> None:
    report = HealthReport(
        status=HealthStatus.UP,
        checks=MappingProxyType(
            {
                "lifecycle": HealthIndicatorResult.up(),
                "queue": HealthIndicatorResult.up(),
                "database": HealthIndicatorResult.up(),
            }
        ),
    )

    checks = report.as_dict()["checks"]
    assert isinstance(checks, dict)
    assert tuple(checks) == ("lifecycle", "queue", "database")
