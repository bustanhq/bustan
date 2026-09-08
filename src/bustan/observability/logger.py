"""Framework logger emitting structured records through the standard library.

One record is one line of JSON on one standard library logging call. That is the whole
of the design, and both halves are load bearing.

JSON, because the previous format was an f-string interpolated into a line and printed:
a message holding a newline arrived at the reader as two lines, the second of which was
a well-formed record of the writer's choosing, attributed to whatever context and
timestamp it wanted. Encoding the record escapes the separator that made that possible,
so a message can no longer end one record and begin another however it is written.

The standard library, because the framework already logs through it everywhere else -
the execution engine, the filters and the guards each hold a ``logging.Logger`` - and
an application that configures logging once should not discover that a second, private
logger ignored the configuration and wrote somewhere else.
"""

from __future__ import annotations

import json
import logging
import sys
from contextlib import contextmanager
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from enum import IntEnum
from typing import TYPE_CHECKING, Any

from .correlation import current_correlation

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

# The logger every record is emitted through. It is the package name, so an application
# configuring "bustan" configures the framework's own records and the records the
# execution engine, the filters and the guards already emit, in one place.
FRAMEWORK_LOGGER_NAME = "bustan"

# What a redacted value is replaced by. A fixed string rather than a removal, so a
# reader can tell a secret that was withheld from a field that was never set.
REDACTED = "[redacted]"

# The field names redacted unless an application says otherwise. Matching folds case
# and nothing else: these are the names a credential is conventionally carried under,
# and a name this list does not hold is a name the application configures.
DEFAULT_REDACTED_KEYS: frozenset[str] = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "cookie",
        "credentials",
        "csrf_token",
        "password",
        "private_key",
        "proxy-authorization",
        "refresh_token",
        "secret",
        "session_id",
        "set-cookie",
        "token",
        "x-api-key",
    }
)

# Structured fields are data a caller assembled, and a caller can assemble a structure
# that refers to itself. Redaction walks it, so the walk is bounded: past this depth a
# value is rendered rather than descended into, which terminates on a cycle and keeps
# an accidental deep structure from costing a request its stack.
MAX_REDACTION_DEPTH = 8


class LogLevel(IntEnum):
    VERBOSE = 0
    DEBUG = 1
    LOG = 2
    WARN = 3
    ERROR = 4


# Framework levels are the ones an application filters on, and the standard library's
# are the ones a handler filters on, so each framework level names the standard level a
# record is emitted at. VERBOSE and DEBUG share one, because the standard library has
# no level below DEBUG that a default configuration passes; the record still carries
# the framework level it was written at, so the two remain distinguishable to a reader.
_STDLIB_LEVELS: dict[LogLevel, int] = {
    LogLevel.VERBOSE: logging.DEBUG,
    LogLevel.DEBUG: logging.DEBUG,
    LogLevel.LOG: logging.INFO,
    LogLevel.WARN: logging.WARNING,
    LogLevel.ERROR: logging.ERROR,
}


class Logger:
    """NestJS-style logger with context labels, level filtering and structured fields.

    Every call emits exactly one record, whatever the message contains. A record
    carries the time, the framework level, the context label, the message, the
    correlation and trace ids of the request in flight when there is one, and whatever
    structured ``fields`` the caller passed, with configured keys redacted.

    An override installed with :meth:`override_logger` or :meth:`scoped_override`
    replaces the destination for the context that installed it and for nothing else,
    so a test that redirects records does not redirect another request's.
    """

    _override: ContextVar[object | None] = ContextVar(
        "bustan_logger_override",
        default=None,
    )
    _override_tokens: ContextVar[tuple[Token[object | None], ...]] = ContextVar(
        "bustan_logger_override_tokens",
        default=(),
    )
    _global_level: LogLevel = LogLevel.LOG
    _redacted_keys: frozenset[str] = DEFAULT_REDACTED_KEYS

    def __init__(self, context: str = "Bustan", *, level: LogLevel | None = None) -> None:
        self._context = context
        self._level = level if level is not None else self._global_level

    def log(self, message: str, context: str | None = None) -> None:
        self._emit(LogLevel.LOG, message, context, None)

    def warn(self, message: str, context: str | None = None) -> None:
        self._emit(LogLevel.WARN, message, context, None)

    def error(
        self,
        message: str,
        trace: str | None = None,
        context: str | None = None,
    ) -> None:
        self._emit(LogLevel.ERROR, message, context, None)
        if trace:
            self._emit(LogLevel.ERROR, trace, context, None)

    def debug(self, message: str, context: str | None = None) -> None:
        self._emit(LogLevel.DEBUG, message, context, None)

    def verbose(self, message: str, context: str | None = None) -> None:
        self._emit(LogLevel.VERBOSE, message, context, None)

    def record(
        self,
        level: LogLevel,
        message: str,
        context: str | None = None,
        *,
        fields: Mapping[str, object] | None = None,
    ) -> None:
        """Write one record at *level*, carrying *fields* as structured data.

        This is the call that takes structured fields, rather than a keyword added to
        each of the five level methods above. Those five are overridden by
        applications and by this framework's own tests, and a parameter added to a
        method someone else has already overridden turns their subclass into one that
        no longer satisfies its base class - a breaking change bought for a keyword.

        Field names are the caller's, and their values are redacted at every depth
        against the configured keys before anything is written.
        """

        self._emit(level, message, context, fields)

    def _emit(
        self,
        level: LogLevel,
        message: str,
        context: str | None,
        fields: Mapping[str, object] | None,
    ) -> None:
        if level < self._level:
            return

        target = self._override.get()
        resolved_context = context or self._context
        if target is not None:
            target_method = getattr(target, level.name.lower(), None) or getattr(  # noqa: B009
                target, "log"
            )
            target_method(message, resolved_context)
            return

        record = build_record(level, message, resolved_context, fields, self._redacted_keys)
        _framework_logger().log(_STDLIB_LEVELS[level], render_record(record))

    @classmethod
    def set_global_level(cls, level: LogLevel) -> None:
        cls._global_level = level

    @classmethod
    def set_redacted_keys(cls, keys: frozenset[str] | set[str] | tuple[str, ...]) -> None:
        """Replace the field names whose values are withheld from every record."""

        cls._redacted_keys = frozenset(key.lower() for key in keys)

    @classmethod
    def override_logger(cls, target: object) -> None:
        """Send records to *target* for the context that calls this.

        The binding is a context variable, so a second task that installs its own
        override neither sees this one nor takes this one's records, and a task that
        installs none keeps writing where it was writing before.
        """

        token = cls._override.set(target)
        cls._override_tokens.set((*cls._override_tokens.get(), token))

    @classmethod
    @contextmanager
    def scoped_override(cls, target: object) -> Iterator[object]:
        """Send records to *target* for the duration of the block."""

        token = cls._override.set(target)
        try:
            yield target
        finally:
            cls._override.reset(token)

    @classmethod
    def reset_logger(cls) -> None:
        """Undo the most recent override, and restore the default level and redaction."""

        cls._global_level = LogLevel.LOG
        cls._redacted_keys = DEFAULT_REDACTED_KEYS
        tokens = cls._override_tokens.get()
        if not tokens:
            cls._override.set(None)
            return

        cls._override.reset(tokens[-1])
        cls._override_tokens.set(tokens[:-1])


def build_record(
    level: LogLevel,
    message: str,
    context: str,
    fields: Mapping[str, object] | None,
    redacted_keys: frozenset[str],
) -> dict[str, object]:
    """Assemble the record one log call emits.

    The framework's own keys are written first and the caller's fields after, and a
    caller's field never replaces one of them: a message that arrives with a "level"
    or a "context" of its own describes something the caller cares about, not the
    record, and letting it win is the same forgery the encoding closes.
    """

    record: dict[str, object] = {
        "timestamp": datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "level": level.name,
        "context": context,
        "message": message,
    }
    correlation = current_correlation()
    if correlation is not None:
        record["correlation_id"] = correlation.correlation_id
        record["trace_id"] = correlation.trace_id
        record["span_id"] = correlation.span_id
    reserved = set(record)
    for key, value in redact(dict(fields or {}), redacted_keys).items():
        if key not in reserved:
            record[key] = value
    return record


def render_record(record: Mapping[str, object]) -> str:
    """Encode *record* as the single line one log call writes.

    ``ensure_ascii`` is on, so every byte written is ASCII and a newline anywhere in
    the record - in the message, in a field name, in a field value - is written as the
    two characters that mean one, and cannot end the line early.
    """

    return json.dumps(record, ensure_ascii=True, default=str, separators=(",", ":"))


def redact(value: object, keys: frozenset[str], depth: int = 0) -> Any:
    """Return *value* with every configured key's value withheld, at any depth.

    A credential is as likely to arrive inside a nested body as at the top of one, so
    the walk descends through mappings and sequences rather than looking only at the
    fields it was handed. Matching folds case, because a header is as often
    ``Authorization`` as ``authorization``, and both name the same secret.
    """

    if depth >= MAX_REDACTION_DEPTH:
        return repr(value)
    if isinstance(value, dict):
        return {
            key: REDACTED if str(key).lower() in keys else redact(item, keys, depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, list | tuple | set | frozenset):
        return [redact(item, keys, depth + 1) for item in value]
    return value


class _BelowLevel(logging.Filter):
    """Passes the records a paired handler at a higher level will not take."""

    def __init__(self, ceiling: int) -> None:
        super().__init__()
        self._ceiling = ceiling

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno < self._ceiling


def _framework_logger() -> logging.Logger:
    """Return the standard library logger records are emitted through.

    An application that has configured logging owns where records go, and this adds
    nothing to what it configured. One that has not would otherwise lose everything
    below a warning to the standard library's default level, so the framework opens
    its own logger and attaches the two handlers that keep the stream split the way an
    operator expects: diagnostics on stdout, warnings and errors on stderr.
    """

    logger = logging.getLogger(FRAMEWORK_LOGGER_NAME)
    if logger.level == logging.NOTSET:
        # Level filtering is LogLevel's job, and a record that reached here already
        # passed it. Opening the standard logger keeps the two from filtering twice.
        logger.setLevel(logging.DEBUG)
    if not logger.handlers and not logging.getLogger().handlers:
        _install_default_handlers(logger)
    return logger


def _install_default_handlers(logger: logging.Logger) -> None:
    """Attach the handlers an unconfigured application gets."""

    formatter = logging.Formatter("%(message)s")
    diagnostics = logging.StreamHandler(sys.stdout)
    diagnostics.setFormatter(formatter)
    diagnostics.addFilter(_BelowLevel(logging.WARNING))
    problems = logging.StreamHandler(sys.stderr)
    problems.setFormatter(formatter)
    problems.setLevel(logging.WARNING)
    logger.addHandler(diagnostics)
    logger.addHandler(problems)


__all__ = [
    "DEFAULT_REDACTED_KEYS",
    "FRAMEWORK_LOGGER_NAME",
    "MAX_REDACTION_DEPTH",
    "REDACTED",
    "LogLevel",
    "Logger",
    "build_record",
    "redact",
    "render_record",
]
