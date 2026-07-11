"""Unit tests for the logger module."""

from __future__ import annotations

from bustan import LogLevel, Logger


def test_logger_writes_messages_with_context(capsys) -> None:
    Logger.reset_logger()
    logger = Logger("App")

    logger.log("hello")

    captured = capsys.readouterr()
    assert "[LOG] [App] hello" in captured.out


def test_logger_respects_log_levels(capsys) -> None:
    Logger.reset_logger()
    logger = Logger("App", level=LogLevel.LOG)

    logger.debug("debug")
    logger.warn("warn")

    captured = capsys.readouterr()
    assert "debug" not in captured.out
    assert "warn" in captured.err


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
