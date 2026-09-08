"""Unit tests for the logger module."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

import anyio
import pytest

from bustan import Logger, LogLevel
from bustan.observability.correlation import (
    RequestCorrelation,
    bind_correlation,
    reset_correlation,
)
from bustan.observability.logger import FRAMEWORK_LOGGER_NAME, REDACTED

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(autouse=True)
def _reset_logger() -> Iterator[None]:
    Logger.reset_logger()
    yield
    Logger.reset_logger()


def _records(caplog: pytest.LogCaptureFixture) -> list[dict[str, object]]:
    """Return the records emitted, decoded from the lines they were written as."""

    return [json.loads(record.getMessage()) for record in caplog.records]


def test_logger_writes_one_structured_record_with_context(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger=FRAMEWORK_LOGGER_NAME)

    Logger("App").log("hello")

    assert [
        (record["level"], record["context"], record["message"]) for record in _records(caplog)
    ] == [("LOG", "App", "hello")]


def test_logger_respects_log_levels(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger=FRAMEWORK_LOGGER_NAME)
    logger = Logger("App", level=LogLevel.LOG)

    logger.debug("debug")
    logger.warn("warn")

    assert [record["message"] for record in _records(caplog)] == ["warn"]
    assert [record.levelno for record in caplog.records] == [logging.WARNING]


def test_a_message_holding_a_newline_is_one_record_not_two(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A user-supplied newline must not be able to end one record and begin another.

    The forged half of the message is a well-formed record of the writer's choosing,
    so the assertion is on the count first: two records here means the reader is being
    told about an ERROR from a context that never logged one.
    """

    caplog.set_level(logging.DEBUG, logger=FRAMEWORK_LOGGER_NAME)
    forged = "[2026-01-01T00:00:00.000Z] [ERROR] [Auth] admin login failed"

    Logger("Probe").log(f"user said: hello\n{forged}")

    emitted = [record.getMessage() for record in caplog.records]
    assert len(emitted) == 1
    assert "\n" not in emitted[0]
    decoded = json.loads(emitted[0])
    assert decoded["level"] == "LOG"
    assert decoded["context"] == "Probe"
    assert decoded["message"] == f"user said: hello\n{forged}"


def test_a_field_a_caller_named_cannot_replace_one_the_framework_writes(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger=FRAMEWORK_LOGGER_NAME)

    Logger("Probe").record(
        LogLevel.LOG,
        "hello",
        fields={"level": "ERROR", "context": "Auth", "route": "/x"},
    )

    record = _records(caplog)[0]
    assert record["level"] == "LOG"
    assert record["context"] == "Probe"
    assert record["route"] == "/x"


def test_configured_keys_are_redacted_including_nested_ones(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger=FRAMEWORK_LOGGER_NAME)

    Logger("Probe").record(
        LogLevel.LOG,
        "signed in",
        fields={
            "user": "ada",
            "Authorization": "Bearer abc",
            "body": {"profile": {"password": "hunter2", "nickname": "ada"}},
            "attempts": [{"token": "t-1"}, {"token": "t-2"}],
        },
    )

    record = _records(caplog)[0]
    assert record["user"] == "ada"
    assert record["Authorization"] == REDACTED
    assert record["body"] == {"profile": {"password": REDACTED, "nickname": "ada"}}
    assert record["attempts"] == [{"token": REDACTED}, {"token": REDACTED}]


def test_redacted_keys_are_configurable(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger=FRAMEWORK_LOGGER_NAME)
    Logger.set_redacted_keys({"account_number"})

    Logger("Probe").record(
        LogLevel.LOG,
        "paid",
        fields={"account_number": "1234", "password": "hunter2"},
    )

    record = _records(caplog)[0]
    assert record["account_number"] == REDACTED
    # The configured set replaces the default rather than adding to it, so a key the
    # application left out is a key the application decided it wanted to see.
    assert record["password"] == "hunter2"


def test_a_self_referential_field_is_rendered_rather_than_followed_forever(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger=FRAMEWORK_LOGGER_NAME)
    cycle: dict[str, object] = {"name": "loop"}
    cycle["self"] = cycle

    Logger("Probe").record(LogLevel.LOG, "cyclic", fields={"cycle": cycle})

    assert _records(caplog)[0]["message"] == "cyclic"


def test_the_correlation_id_of_the_request_in_flight_reaches_every_record(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger=FRAMEWORK_LOGGER_NAME)
    token = bind_correlation(
        RequestCorrelation(
            correlation_id="req-42",
            trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
            span_id="00f067aa0ba902b7",
        )
    )
    try:
        Logger("Probe").log("hello")
    finally:
        reset_correlation(token)

    record = _records(caplog)[0]
    assert record["correlation_id"] == "req-42"
    assert record["trace_id"] == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert record["span_id"] == "00f067aa0ba902b7"


def test_a_record_written_outside_a_request_names_no_correlation(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger=FRAMEWORK_LOGGER_NAME)

    Logger("Probe").log("hello")

    assert "correlation_id" not in _records(caplog)[0]


def test_logger_override_redirects_output() -> None:
    class Recorder:
        def __init__(self) -> None:
            self.messages: list[tuple[str, str]] = []

        def log(self, message: str, context: str) -> None:
            self.messages.append((context, message))

    recorder = Recorder()
    Logger.override_logger(recorder)
    try:
        Logger("App").log("hello")
    finally:
        Logger.reset_logger()

    assert recorder.messages == [("App", "hello")]


def test_scoped_override_restores_the_previous_destination(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger=FRAMEWORK_LOGGER_NAME)

    class Recorder:
        def __init__(self) -> None:
            self.messages: list[str] = []

        def log(self, message: str, context: str) -> None:
            self.messages.append(message)

    recorder = Recorder()
    with Logger.scoped_override(recorder):
        Logger("App").log("inside")
    Logger("App").log("outside")

    assert recorder.messages == ["inside"]
    assert [record["message"] for record in _records(caplog)] == ["outside"]


def test_an_override_in_one_task_neither_leaks_into_nor_steals_from_another() -> None:
    """Two concurrent tasks, each with its own override, keep their own records.

    Both halves are asserted. The defect this closes did not merely leak one task's
    override into the other: it redirected the losing task's records into the winner's
    sink, so the losing task captured nothing at all. A test that only asserted that
    B never saw A's record would still pass while A's records were being dropped.
    """

    class Capture:
        def __init__(self) -> None:
            self.messages: list[str] = []

        def log(self, message: str, context: str) -> None:
            self.messages.append(message)

    captures: dict[str, Capture] = {"A": Capture(), "B": Capture()}

    async def serve(name: str, installed: anyio.Event, other: anyio.Event) -> None:
        Logger.override_logger(captures[name])
        installed.set()
        # Neither task logs until both overrides are installed, so the interleaving
        # that produced the defect is the one the test runs, not one it hopes for.
        await other.wait()
        Logger("Probe").log(f"from-{name}")

    async def main() -> None:
        installed_a, installed_b = anyio.Event(), anyio.Event()
        async with anyio.create_task_group() as task_group:
            task_group.start_soon(serve, "A", installed_a, installed_b)
            task_group.start_soon(serve, "B", installed_b, installed_a)

    anyio.run(main)

    assert captures["A"].messages == ["from-A"]
    assert captures["B"].messages == ["from-B"]


def test_logger_covers_error_trace_debug_verbose_and_global_level_override() -> None:
    class Recorder:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, str]] = []

        def log(self, message: str, context: str) -> None:
            self.calls.append(("log", context, message))

        def error(self, message: str, context: str) -> None:
            self.calls.append(("error", context, message))

    recorder = Recorder()
    Logger.set_global_level(LogLevel.VERBOSE)
    Logger.override_logger(recorder)
    try:
        logger = Logger("App")
        logger.error("boom", trace="stack")
        logger.debug("debug", context="Debug")
        logger.verbose("verbose")
    finally:
        Logger.reset_logger()

    assert recorder.calls == [
        ("error", "App", "boom"),
        ("error", "App", "stack"),
        ("log", "Debug", "debug"),
        ("log", "App", "verbose"),
    ]


def test_an_unconfigured_application_still_gets_records_on_the_right_streams(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """With no logging configured at all, records still reach an operator.

    The test takes the configuration away that the suite installs, because the
    behaviour under test is what a plain ``python -m`` process does, and under pytest
    the root logger always has a handler.
    """

    framework_logger = logging.getLogger(FRAMEWORK_LOGGER_NAME)
    root = logging.getLogger()
    saved = (framework_logger.handlers[:], framework_logger.level, root.handlers[:])
    framework_logger.handlers.clear()
    framework_logger.setLevel(logging.NOTSET)
    root.handlers.clear()
    try:
        logger = Logger("App", level=LogLevel.VERBOSE)
        logger.log("diagnostic")
        logger.error("problem")
    finally:
        framework_logger.handlers[:] = saved[0]
        framework_logger.setLevel(saved[1])
        root.handlers[:] = saved[2]

    captured = capsys.readouterr()
    assert json.loads(captured.out.strip())["message"] == "diagnostic"
    assert json.loads(captured.err.strip())["message"] == "problem"
