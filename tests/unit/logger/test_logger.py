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
