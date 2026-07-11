"""Route-aware observability hooks for request execution."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar, Token
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
    ) -> None:
        self._metrics = metrics
        self._tracer = tracer

    @classmethod
    def current(cls) -> "ObservabilityHooks":
        return cls._override.get() or cls()

    @classmethod
    def override_global(cls, hooks: "ObservabilityHooks") -> None:
        token = cls._override.set(hooks)
        cls._override_tokens.set(cls._override_tokens.get() + (token,))

    @classmethod
    @contextmanager
    def scoped_override(cls, hooks: "ObservabilityHooks") -> Iterator["ObservabilityHooks"]:
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


__all__ = ["ActiveObservation", "MetricsSink", "ObservabilityHooks", "RequestTracer", "TraceSpan", "build_route_labels"]
