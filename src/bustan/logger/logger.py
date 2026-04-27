"""Simple framework logger with overridable sinks."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from enum import IntEnum


class LogLevel(IntEnum):
    VERBOSE = 0
    DEBUG = 1
    LOG = 2
    WARN = 3
    ERROR = 4


class Logger:
    """NestJS-style logger with context labels and level filtering."""

    _override: object | None = None
    _global_level: LogLevel = LogLevel.LOG

    def __init__(self, context: str = "Bustan", *, level: LogLevel | None = None) -> None:
        self._context = context
        self._level = level if level is not None else self._global_level

    def log(self, message: str, context: str | None = None) -> None:
        self._emit(LogLevel.LOG, message, context)

    def warn(self, message: str, context: str | None = None) -> None:
        self._emit(LogLevel.WARN, message, context)

    def error(
        self,
        message: str,
        trace: str | None = None,
        context: str | None = None,
    ) -> None:
        self._emit(LogLevel.ERROR, message, context)
        if trace:
            self._emit(LogLevel.ERROR, trace, context)

    def debug(self, message: str, context: str | None = None) -> None:
        self._emit(LogLevel.DEBUG, message, context)

    def verbose(self, message: str, context: str | None = None) -> None:
        self._emit(LogLevel.VERBOSE, message, context)

    def _emit(self, level: LogLevel, message: str, context: str | None) -> None:
        if level < self._level:
            return

        target = self._override
        resolved_context = context or self._context
        if target is not None:
            target_method = getattr(target, level.name.lower(), None) or getattr(target, "log")
            target_method(message, resolved_context)
            return

        timestamp = datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        output = f"[{timestamp}] [{level.name}] [{resolved_context}] {message}"
        stream = sys.stderr if level >= LogLevel.WARN else sys.stdout
        print(output, file=stream)

    @classmethod
    def set_global_level(cls, level: LogLevel) -> None:
        cls._global_level = level

    @classmethod
    def override_logger(cls, target: object) -> None:
        cls._override = target

    @classmethod
    def reset_logger(cls) -> None:
        cls._override = None
        cls._global_level = LogLevel.LOG
