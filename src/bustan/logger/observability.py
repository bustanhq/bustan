"""Route-aware observability hooks for request execution."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from ..pipeline.context import ExecutionContext


class MetricsSink(Protocol):
    """Metric sink used by the observability hooks."""

    def record_request(self, *, labels: Mapping[str, str]) -> None:
        pass


class TraceSpan(Protocol):
    """Minimal tracing span contract used by the runtime."""

    def finish(self, *, status_code: int, error: Exception | None = None) -> None:
        pass


class RequestTracer(Protocol):
    """Minimal tracer contract used by the runtime."""

    def start_span(self, name: str, *, labels: Mapping[str, str]) -> TraceSpan:
        pass


@dataclass(frozen=True, slots=True)
class ActiveObservation:
    """Active request observation state."""

    labels: dict[str, str]
    span: TraceSpan | None = None


class ObservabilityHooks:
    """Route-aware metrics and tracing hooks around request execution."""

    _override: "ObservabilityHooks | None" = None

    def __init__(
        self,
        *,
        metrics: MetricsSink | None = None,
        tracer: RequestTracer | None = None,
    ) -> None:
        self._metrics = metrics
        self._tracer = tracer

    @classmethod
    def current(cls) -> "ObservabilityHooks":
        return cls._override or cls()

    @classmethod
    def override_global(cls, hooks: "ObservabilityHooks") -> None:
        cls._override = hooks

    @classmethod
    def reset_global(cls) -> None:
        cls._override = None

    def start_request(self, context: ExecutionContext) -> ActiveObservation:
        labels = build_route_labels(context.get_route_contract())
        span = None
        if self._tracer is not None:
            span = self._tracer.start_span(labels["operation"], labels=labels)
        return ActiveObservation(labels=labels, span=span)

    def finish_request(
        self,
        observation: ActiveObservation,
        *,
        status_code: int,
        error: Exception | None = None,
    ) -> None:
        labels = {**observation.labels, "status": str(status_code)}
        if self._metrics is not None:
            self._metrics.record_request(labels=labels)
        if observation.span is not None:
            observation.span.finish(status_code=status_code, error=error)


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
        controller_cls = getattr(route_contract, "controller_cls")
        labels = {
            "controller": controller_cls.__name__,
            "route": f"{getattr(route_contract, 'method')} {getattr(route_contract, 'path')}",
            "operation": f"{controller_cls.__name__}.{getattr(route_contract, 'handler_name')}",
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


__all__ = ["ActiveObservation", "MetricsSink", "ObservabilityHooks", "RequestTracer", "TraceSpan", "build_route_labels"]