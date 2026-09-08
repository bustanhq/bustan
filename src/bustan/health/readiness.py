"""The two lifecycle edges readiness turns on, and the check that reports them."""

from __future__ import annotations

from ..common.decorators.injectable import Injectable
from .indicators import HealthIndicatorResult

LIFECYCLE_CHECK_NAME = "lifecycle"


@Injectable
class ReadinessState:
    """Where this process is in its own lifetime, as far as routing traffic goes.

    Two edges, and readiness is false outside the span between them.

    **Started.** Set by the application bootstrap hook, which runs after every module
    and provider has been initialized. Until then the process is alive but has not
    finished assembling itself, and traffic sent to it would be served by an
    application that is still being built.

    **Draining.** Set when the process is asked to stop. Nothing in the lifecycle
    records this on its own: a process that has been asked to stop is still fully
    initialized and is still finishing the requests it already accepted, while it must
    stop being sent new ones. Closing that gap is what this edge is for. The teardown
    hook sets it as a backstop, so a shutdown nobody announced still withdraws the
    process; a shutdown sequence that wants the process out of rotation *before* it
    stops serving has to say so earlier, which is what ``begin_drain`` is for.

    **The contract for whoever owns the shutdown sequence.** On a termination signal,
    call ``begin_drain`` first, before the teardown hooks run and before any request is
    refused, and only then wait for in-flight requests to finish. That order is the
    whole point: readiness has to go false while the process is still serving normally,
    so traffic is withdrawn from it by whatever routes traffic before it stops being
    able to accept any. Draining only as part of teardown would take the process out of
    rotation once it had already stopped serving, which is the outage this prevents.
    An application that does not provide this state has no readiness probe either, so a
    shutdown sequence that cannot resolve it has nothing to flip and drains without it.

    Both edges are one-way within a lifecycle, and neither survives one: teardown drops
    every instance the application built, so an application that is started again is
    served by a new state that has neither edge set.
    """

    __slots__ = ("_draining", "_started")

    def __init__(self) -> None:
        self._started = False
        self._draining = False

    @property
    def started(self) -> bool:
        """Whether the application has finished starting up."""

        return self._started

    @property
    def draining(self) -> bool:
        """Whether this process has been asked to stop and wants no further traffic."""

        return self._draining

    def begin_drain(self) -> None:
        """Record that the process is draining. Idempotent, and never reversed."""

        self._draining = True

    def on_application_bootstrap(self) -> None:
        """Record that startup reached the last stage the application runs."""

        self._started = True

    def before_application_shutdown(self, signal: str | None) -> None:
        """Record that the process is going away, if nothing said so earlier."""

        self._draining = True


class LifecycleIndicator:
    """Built-in readiness check: has this process started, and does it still want traffic.

    Registered first on every readiness probe, so a report says which of the two edges
    withheld readiness rather than leaving a reader to infer it from an empty check
    list. Liveness never consults it: a process that has not finished starting and a
    process that is draining are both alive, and restarting either one for being unready
    turns an orderly deploy into a crash loop.

    It answers for the application's own lifecycle and for nothing else. A component
    whose startup work must hold traffic back until it finishes registers its own
    readiness indicator, and registers it while modules are initializing, which is
    before any hook can report the application started.
    """

    __slots__ = ("_state",)

    def __init__(self, state: ReadinessState) -> None:
        self._state = state

    @property
    def name(self) -> str:
        """Key this check is reported under."""

        return LIFECYCLE_CHECK_NAME

    async def check(self) -> HealthIndicatorResult:
        """Report down while startup is unfinished, or once the process is draining."""

        # Draining is reported ahead of startup because it is the answer that cannot
        # change: a process asked to stop mid-startup is going away either way.
        if self._state.draining:
            return HealthIndicatorResult.down("the process is draining")
        if not self._state.started:
            return HealthIndicatorResult.down("startup has not completed")
        return HealthIndicatorResult.up()


__all__ = (
    "LIFECYCLE_CHECK_NAME",
    "LifecycleIndicator",
    "ReadinessState",
)
