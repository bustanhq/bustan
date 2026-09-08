"""Correlation and trace context carried across one request.

A request that touches several services, or merely several log records, is only
readable afterwards if every record it produced names the same request. That name is
the correlation id, and this module is where one comes from: taken from the caller
when the caller supplied one, generated when it did not, and bound to the context for
the whole of the request so that neither the logger nor the tracer has to be handed it.

The trace identifiers live here for the same reason and travel the same way. Incoming
W3C ``traceparent`` headers are parsed into the trace this request belongs to, so a
span this process starts joins the caller's trace instead of beginning a new one, and
the caller's sampling decision is available to whoever makes ours.

Nothing here writes anything. It holds the identity of the request in flight, and the
logger and the observability hooks read it.
"""

from __future__ import annotations

import re
from contextvars import ContextVar, Token
from dataclasses import dataclass
from secrets import token_hex
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

# The headers a caller can name this request with, in the order they are consulted.
# The first is what this framework emits and documents; the second is what proxies and
# other frameworks commonly set, and honouring it costs nothing.
CORRELATION_ID_HEADERS: tuple[str, ...] = ("x-correlation-id", "x-request-id")
TRACEPARENT_HEADER = "traceparent"

# A correlation id reaches log records, so what a caller may put in one is bounded
# before it is stored rather than after. Printable ASCII keeps a record readable and
# the length cap keeps one caller from paying for another's storage; anything outside
# either is not repaired, it is replaced by a generated id, because a half-accepted
# identifier is worse than an honest one the caller can be told about.
MAX_CORRELATION_ID_LENGTH = 128
_CORRELATION_ID_PATTERN = re.compile(f"\\A[\\x21-\\x7e]{{1,{MAX_CORRELATION_ID_LENGTH}}}\\Z")

# W3C Trace Context, version 00: two hex digits of version, a 32 hex digit trace id, a
# 16 hex digit parent span id and two hex digits of flags, separated by hyphens. A
# version of "ff" is invalid by the specification, and an all-zero id in either
# position means the sender had none, so both are refused rather than propagated.
_TRACEPARENT_PATTERN = re.compile(
    r"\A(?P<version>[0-9a-f]{2})-(?P<trace_id>[0-9a-f]{32})-"
    r"(?P<span_id>[0-9a-f]{16})-(?P<flags>[0-9a-f]{2})\Z"
)
_ZERO_TRACE_ID = "0" * 32
_ZERO_SPAN_ID = "0" * 16
_SAMPLED_FLAG = 0x01


@dataclass(frozen=True, slots=True)
class RequestCorrelation:
    """The identity of one request in flight.

    ``correlation_id`` names the request in every log record it produces.
    ``trace_id`` and ``span_id`` name the server span this process runs for it.
    ``parent_span_id`` is the caller's span when the caller sent a ``traceparent``,
    and ``parent_sampled`` is the caller's sampling decision, which is ``None`` when
    there was no caller to make one.
    """

    correlation_id: str
    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    parent_sampled: bool | None = None

    def traceparent(self) -> str:
        """Return the ``traceparent`` header naming this request's server span."""

        return f"00-{self.trace_id}-{self.span_id}-01"


_CORRELATION: ContextVar[RequestCorrelation | None] = ContextVar(
    "bustan_request_correlation",
    default=None,
)


def current_correlation() -> RequestCorrelation | None:
    """Return the correlation bound to the request in flight, or ``None``."""

    return _CORRELATION.get()


def current_correlation_id() -> str | None:
    """Return the correlation id of the request in flight, or ``None``."""

    correlation = _CORRELATION.get()
    return None if correlation is None else correlation.correlation_id


def bind_correlation(correlation: RequestCorrelation) -> Token[RequestCorrelation | None]:
    """Bind *correlation* for the context that calls this, and return its token.

    The binding is a context variable rather than process state, so one request's
    identity is invisible to every other request in flight, and two served at the same
    time cannot be confused for one another.
    """

    return _CORRELATION.set(correlation)


def reset_correlation(token: Token[RequestCorrelation | None]) -> None:
    """Undo the binding *token* was returned for."""

    _CORRELATION.reset(token)


def correlation_from_headers(headers: Mapping[str, str]) -> RequestCorrelation:
    """Build the correlation for a request arriving with *headers*.

    The caller's correlation id is honoured when it is one this framework is willing
    to write into a log record, and a fresh one is generated otherwise. A valid
    ``traceparent`` joins this request to the caller's trace and carries the caller's
    sampling decision forward; anything else starts a new trace here.
    """

    parent = parse_traceparent(_header(headers, TRACEPARENT_HEADER))
    trace_id = new_trace_id() if parent is None else parent.trace_id
    return RequestCorrelation(
        correlation_id=_accepted_correlation_id(headers) or new_correlation_id(),
        trace_id=trace_id,
        span_id=new_span_id(),
        parent_span_id=None if parent is None else parent.span_id,
        parent_sampled=None if parent is None else parent.sampled,
    )


@dataclass(frozen=True, slots=True)
class _Traceparent:
    """What a well-formed incoming ``traceparent`` header said."""

    trace_id: str
    span_id: str
    sampled: bool


def parse_traceparent(value: str | None) -> _Traceparent | None:
    """Return what *value* says, or ``None`` when it says nothing usable.

    A malformed header is not an error the caller is told about. The specification
    says a receiver that cannot parse one starts a new trace, which is what returning
    ``None`` here makes the caller do, and a request is still served either way.
    """

    if value is None:
        return None
    match = _TRACEPARENT_PATTERN.match(value.strip().lower())
    if match is None:
        return None
    if match["version"] == "ff":
        return None
    if match["trace_id"] == _ZERO_TRACE_ID or match["span_id"] == _ZERO_SPAN_ID:
        return None
    return _Traceparent(
        trace_id=match["trace_id"],
        span_id=match["span_id"],
        sampled=bool(int(match["flags"], 16) & _SAMPLED_FLAG),
    )


def new_correlation_id() -> str:
    """Return a correlation id for a request that arrived without one."""

    return token_hex(16)


def new_trace_id() -> str:
    """Return a trace id for a request that did not arrive inside a trace."""

    return token_hex(16)


def new_span_id() -> str:
    """Return a span id for a span this process is about to start."""

    return token_hex(8)


def trace_id_sampled(trace_id: str, ratio: float) -> bool:
    """Return whether *trace_id* falls inside a head sampling *ratio*.

    The decision is a function of the trace id and nothing else, so every service that
    sees the same trace and is configured with the same ratio decides the same way and
    a trace is sampled whole rather than in pieces. A ratio of 1 keeps everything and
    a ratio of 0 keeps nothing, without consulting the id at all.
    """

    if ratio >= 1.0:
        return True
    if ratio <= 0.0:
        return False
    return int(trace_id[16:], 16) < int(ratio * (1 << 64))


def _accepted_correlation_id(headers: Mapping[str, str]) -> str | None:
    """Return the first correlation id in *headers* this framework will store."""

    for name in CORRELATION_ID_HEADERS:
        value = _header(headers, name)
        if value is not None and _CORRELATION_ID_PATTERN.match(value):
            return value
    return None


def _header(headers: Mapping[str, str], name: str) -> str | None:
    """Read *name* from *headers* whether or not the mapping folds case itself."""

    value = headers.get(name)
    if value is not None:
        return value
    for key, candidate in headers.items():
        if key.lower() == name:
            return candidate
    return None


__all__ = [
    "CORRELATION_ID_HEADERS",
    "MAX_CORRELATION_ID_LENGTH",
    "TRACEPARENT_HEADER",
    "RequestCorrelation",
    "bind_correlation",
    "correlation_from_headers",
    "current_correlation",
    "current_correlation_id",
    "new_correlation_id",
    "new_span_id",
    "new_trace_id",
    "parse_traceparent",
    "reset_correlation",
    "trace_id_sampled",
]
