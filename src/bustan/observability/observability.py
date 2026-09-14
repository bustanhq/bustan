"""Route-aware observability hooks for request execution."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from enum import StrEnum
from time import perf_counter
from typing import TYPE_CHECKING, Protocol, cast

from .correlation import (
    RequestCorrelation,
    current_correlation,
    new_correlation_id,
    new_span_id,
    new_trace_id,
    trace_id_sampled,
)

if TYPE_CHECKING:
    from ..pipeline.context import ExecutionContext

# The status a server span carries when the request failed. OpenTelemetry leaves a
# server span UNSET for a 4xx, because a refused request is the server working, and
# marks only the failures the server owns; ERROR is therefore reserved for a 5xx or
# for a request that ended in an exception.
_SERVER_ERROR_STATUS = 500


class SpanKind(StrEnum):
    """Where a span sits in a call, in OpenTelemetry's terms."""

    INTERNAL = "internal"
    SERVER = "server"
    CLIENT = "client"
    PRODUCER = "producer"
    CONSUMER = "consumer"


class SpanStatus(StrEnum):
    """The outcome a finished span reports."""

    UNSET = "unset"
    OK = "ok"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class SpanContext:
    """The identity of one span and the trace it belongs to.

    ``sampled`` is the head sampling decision, made once when the span starts and true
    for the whole trace: a caller that sampled a request is honoured, and a request
    that arrived without a decision gets one from the configured ratio.
    """

    trace_id: str
    span_id: str
    sampled: bool
    parent_span_id: str | None = None


class MetricsSink(Protocol):
    """Metric sink used by the observability hooks.

    One call per finished request, carrying the route labels, the status it was
    answered with, and how long it took in seconds.
    """

    def record_request(self, *, labels: Mapping[str, str], duration_seconds: float) -> None:
        pass


class TraceSpan(Protocol):
    """A span, in OpenTelemetry's terms: attributes, a status, and an end.

    The runtime sets attributes while the request runs, records the exception when
    there was one, sets the status once, and ends the span exactly once.
    """

    def set_attribute(self, key: str, value: object) -> None:
        pass

    def set_status(self, status: SpanStatus, *, description: str | None = None) -> None:
        pass

    def record_exception(self, error: BaseException) -> None:
        pass

    def end(self) -> None:
        pass


class RequestTracer(Protocol):
    """Tracer contract used by the runtime.

    ``context`` names the trace the span belongs to and the caller's span when the
    request arrived inside a trace, so a span this process starts continues the
    caller's trace rather than beginning one beside it.
    """

    def start_span(
        self,
        name: str,
        *,
        kind: SpanKind,
        attributes: Mapping[str, str],
        context: SpanContext,
    ) -> TraceSpan:
        pass


@dataclass(frozen=True, slots=True)
class ActiveObservation:
    """Active request observation state.

    ``started_at`` is a monotonic reading taken when the request was admitted, which
    is what makes the duration a measurement of the request rather than a difference
    between two wall clocks that can move under it.

    ``labels`` belongs to the route rather than to the request: every observation one
    hooks object starts for a route carries the same dictionary, so nothing writes to it.
    """

    labels: dict[str, str]
    started_at: float = field(default_factory=perf_counter)
    span: TraceSpan | None = None
    span_context: SpanContext | None = None


# What hooks with no metrics sink and no tracer start for every request. Those hooks
# finish an observation without reading it, so one serves every request, and it holds
# no labels, no span context and no clock reading because nothing is there to use them.
_UNOBSERVED_REQUEST = ActiveObservation(labels={}, started_at=0.0)


class ObservabilityHooks:
    """Route-aware metrics and tracing hooks around request execution."""

    _override: ContextVar[ObservabilityHooks | None] = ContextVar(
        "bustan_observability_hooks_override",
        default=None,
    )
    _override_tokens: ContextVar[tuple[Token[ObservabilityHooks | None], ...]] = ContextVar(
        "bustan_observability_hooks_override_tokens",
        default=(),
    )

    def __init__(
        self,
        *,
        metrics: MetricsSink | None = None,
        tracer: RequestTracer | None = None,
        sample_ratio: float = 1.0,
    ) -> None:
        self._metrics = metrics
        self._tracer = tracer
        self._sample_ratio = sample_ratio
        self._metrics_takes_duration = metrics is None or _takes_duration(metrics)
        # A route's labels, built the first time these hooks observe it and filed under
        # the identity of its contract, because hashing a contract hashes every plan it
        # holds. Each entry keeps its contract alive, so no other object can take the id
        # it is filed under while the entry exists. Contracts are compiled when an
        # application is created, so the table grows with routes, never with requests.
        self._route_labels: dict[int, tuple[object | None, dict[str, str]]] = {}

    @classmethod
    def current(cls) -> ObservabilityHooks:
        return cls._override.get() or cls()

    @classmethod
    def resolve(cls, configured: ObservabilityHooks | None) -> ObservabilityHooks:
        """Return the hooks one request is served under.

        An override installed for the calling context wins, because that is what an
        override is for: a test that redirects a request's metrics has to be able to
        do so whatever the application it is testing was assembled with. Otherwise
        the application serves under the hooks it was given, and an application given
        none serves under hooks that record nothing rather than under no hooks at all.
        """

        return cls._override.get() or configured or _SILENT_HOOKS

    @classmethod
    def override_global(cls, hooks: ObservabilityHooks) -> None:
        token = cls._override.set(hooks)
        cls._override_tokens.set(cls._override_tokens.get() + (token,))

    @classmethod
    @contextmanager
    def scoped_override(cls, hooks: ObservabilityHooks) -> Iterator[ObservabilityHooks]:
        token = cls._override.set(hooks)
        try:
            yield hooks
        finally:
            cls._override.reset(token)

    @classmethod
    def reset_global(cls) -> None:
        tokens = cls._override_tokens.get()
        if not tokens:
            cls._override.set(None)
            return

        cls._override.reset(tokens[-1])
        cls._override_tokens.set(tokens[:-1])

    def start_request(self, context: ExecutionContext) -> ActiveObservation:
        """Begin observing one request, and start its server span when it is sampled.

        Head sampling decides whether a span is started, not whether the request is
        measured. With a metrics sink attached an unsampled request is still measured
        and counted, because the metric is what every request costs and the span is
        what one request is worth keeping. Hooks with a tracer and no metrics sink
        measure and count nothing for an unsampled request: no span was started for it,
        and no sink is attached to record it.
        """

        if self._metrics is None and self._tracer is None:
            return _UNOBSERVED_REQUEST
        labels = self._labels_for(context.get_route_contract())
        correlation = current_correlation() or _unbound_correlation()
        span_context = SpanContext(
            trace_id=correlation.trace_id,
            span_id=correlation.span_id,
            sampled=self._sampled(correlation),
            parent_span_id=correlation.parent_span_id,
        )
        span = None
        if self._tracer is not None and span_context.sampled:
            span = self._tracer.start_span(
                labels["operation"],
                kind=SpanKind.SERVER,
                attributes={**labels, "correlation_id": correlation.correlation_id},
                context=span_context,
            )
        return ActiveObservation(
            labels=labels,
            started_at=perf_counter(),
            span=span,
            span_context=span_context,
        )

    def finish_request(
        self,
        observation: ActiveObservation,
        *,
        status_code: int,
        error: Exception | None = None,
    ) -> None:
        """Close one request's observation, whatever it was answered with.

        The duration is the elapsed time since the observation began, so it covers
        everything the request paid for - the guards, the provider resolution, the
        body, the handler and rendering the answer - and not merely the handler.
        """

        # With no sink to record it and no span to end, a duration would go nowhere.
        if self._metrics is None and observation.span is None:
            return
        duration_seconds = max(perf_counter() - observation.started_at, 0.0)
        if self._metrics is not None:
            # A new dictionary for every record: a sink may keep or change what it is
            # given, and the route's own labels are shared by all of its requests.
            labels = {**observation.labels, "status": str(status_code)}
            self._record(self._metrics, labels, duration_seconds)
        if observation.span is not None:
            self._finish_span(observation.span, status_code, duration_seconds, error)

    def _record(
        self,
        metrics: MetricsSink,
        labels: dict[str, str],
        duration_seconds: float,
    ) -> None:
        """Hand one finished request to the metric sink."""

        if self._metrics_takes_duration:
            metrics.record_request(labels=labels, duration_seconds=duration_seconds)
            return
        # A sink written against the contract that had no duration is still a sink,
        # and the runtime measures the duration either way. Handing it what it accepts
        # keeps it working rather than turning the new field into a TypeError on a
        # path that only runs once the response has already been decided.
        legacy_record = cast(Callable[..., None], metrics.record_request)
        legacy_record(labels=labels)

    def _finish_span(
        self,
        span: TraceSpan,
        status_code: int,
        duration_seconds: float,
        error: Exception | None,
    ) -> None:
        """End one server span with the outcome its request had."""

        span.set_attribute("http.status_code", status_code)
        span.set_attribute("duration_seconds", duration_seconds)
        if error is not None:
            span.record_exception(error)
            span.set_status(SpanStatus.ERROR, description=f"{type(error).__name__}: {error}")
        elif status_code >= _SERVER_ERROR_STATUS:
            span.set_status(SpanStatus.ERROR, description=f"status {status_code}")
        else:
            span.set_status(SpanStatus.UNSET)
        span.end()

    def _sampled(self, correlation: RequestCorrelation) -> bool:
        """Decide whether this request's span is kept."""

        if correlation.parent_sampled is not None:
            return correlation.parent_sampled
        return trace_id_sampled(correlation.trace_id, self._sample_ratio)

    def _labels_for(self, route_contract: object | None) -> dict[str, str]:
        """Return *route_contract*'s labels, built the first time these hooks see it."""

        key = id(route_contract)
        entry = self._route_labels.get(key)
        if entry is None:
            entry = (route_contract, build_route_labels(route_contract))
            self._route_labels[key] = entry
        return entry[1]


# The hooks an application that declared none is served under. Without a sink or a
# tracer they keep nothing from one request to the next, so every such application
# shares this one rather than building hooks for each request it serves.
_SILENT_HOOKS = ObservabilityHooks()


def _unbound_correlation() -> RequestCorrelation:
    """Return identifiers for an observation started outside a served request.

    The hooks are usable on their own, and a span still needs a trace to belong to, so
    one is minted here rather than left blank. It is deliberately not bound to the
    context: nothing else is part of this request, so nothing else should join it.
    """

    return RequestCorrelation(
        correlation_id=new_correlation_id(),
        trace_id=new_trace_id(),
        span_id=new_span_id(),
    )


def _takes_duration(metrics: MetricsSink) -> bool:
    """Return whether *metrics* accepts the duration keyword the runtime measures."""

    try:
        parameters = inspect.signature(metrics.record_request).parameters
    except (TypeError, ValueError):
        # Anything whose signature cannot be read is taken at the current contract,
        # because the alternative is to permanently downgrade every callable sink that
        # a signature cannot be recovered from, such as one behind a C accelerator.
        return True
    if any(parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()):
        return True
    return "duration_seconds" in parameters


def build_route_labels(
    route_contract: object | None,
    *,
    status_code: int | None = None,
) -> dict[str, str]:
    if route_contract is None:
        labels = {
            "controller": "unknown",
            "route": "unknown",
            "operation": "unknown",
            "version": "neutral",
        }
    else:
        controller_cls = getattr(route_contract, "controller_cls", None)
        controller_name = getattr(controller_cls, "__name__", "unknown")
        method = getattr(route_contract, "method", None)
        path = getattr(route_contract, "path", None)
        handler_name = getattr(route_contract, "handler_name", None)
        labels = {
            "controller": controller_name,
            "route": "unknown" if method is None or path is None else f"{method} {path}",
            "operation": (
                "unknown"
                if controller_name == "unknown" or handler_name is None
                else f"{controller_name}.{handler_name}"
            ),
            "version": _route_version_label(route_contract),
        }

    if status_code is not None:
        labels["status"] = str(status_code)
    return labels


def _route_version_label(route_contract: object) -> str:
    versions = tuple(getattr(route_contract, "versions", ()))
    if not versions:
        return "neutral"
    return ",".join(versions)


__all__ = [
    "ActiveObservation",
    "MetricsSink",
    "ObservabilityHooks",
    "RequestTracer",
    "SpanContext",
    "SpanKind",
    "SpanStatus",
    "TraceSpan",
    "build_route_labels",
]
