"""Aggregation across registered indicators, and the two probes it answers."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from types import MappingProxyType

from ..observability.logger import Logger
from .indicators import HealthIndicator, HealthIndicatorResult, HealthReport, HealthStatus
from .readiness import LifecycleIndicator, ReadinessState

# A probe is read on a fixed interval by something that will act on a missing answer, so
# a check has to be given less time than the caller is prepared to wait. Five seconds is
# under the interval any common probe configuration uses and above any healthy check.
DEFAULT_CHECK_TIMEOUT = 5.0


class HealthService:
    """Registers health indicators and answers the liveness and readiness probes.

    The two probes answer different questions and share no indicators, because the two
    answers cause different things to happen.

    **Liveness** answers whether the process is alive, and the only honest evidence for
    that is that it answered at all. It therefore starts up, and stays, with nothing
    registered against it: no dependency belongs here, because a failing dependency is
    not a reason to kill and restart a process that is working. Register a liveness
    indicator only for a fault the process has detected in itself and cannot recover
    from without being restarted.

    **Readiness** answers whether this pod should be sent traffic. It always begins with
    the built-in lifecycle check, which is down before startup finishes and down again
    once the process is draining, and adds every dependency the process needs in order
    to serve a request correctly. A readiness indicator going down takes one pod out of
    rotation, which is recoverable; that is why the dependencies belong here.

    Every indicator of a probe is checked on each read, and they are checked together,
    so one slow dependency does not delay the answer about the others.

    A registered indicator cannot take a probe down. One that raises, one that does not
    answer within the check timeout, and one that answers with something that is not a
    result are each recorded as a down check under their own name, and the probe still
    reports on every other indicator. The failure is logged in full; what reaches the
    caller of the probe names only the kind of failure, because anything that can reach
    a probe reads its response.
    """

    __slots__ = ("_check_timeout", "_liveness", "_logger", "_readiness")

    def __init__(
        self,
        readiness_state: ReadinessState,
        *,
        check_timeout: float = DEFAULT_CHECK_TIMEOUT,
        logger: Logger | None = None,
    ) -> None:
        if check_timeout <= 0:
            raise ValueError(
                f"check_timeout must be a positive number of seconds, not {check_timeout!r}"
            )
        self._check_timeout = check_timeout
        self._logger = logger if logger is not None else Logger("Health")
        lifecycle = LifecycleIndicator(readiness_state)
        self._liveness: dict[str, HealthIndicator] = {}
        self._readiness: dict[str, HealthIndicator] = {lifecycle.name: lifecycle}

    def register_liveness(self, indicator: HealthIndicator) -> None:
        """Register an indicator for a fault only a restart can clear.

        Registering a dependency here instead of on readiness is the mistake this
        method exists to be deliberate about: it turns an outage in something else into
        a restart of this process, which cannot fix it and loses everything in flight.
        """

        self._register(self._liveness, indicator, "liveness")

    def register_readiness(self, indicator: HealthIndicator) -> None:
        """Register an indicator for something this process needs in order to serve."""

        self._register(self._readiness, indicator, "readiness")

    async def liveness(self) -> HealthReport:
        """Report whether the process is alive, consulting nothing about its lifecycle.

        Startup and drain are deliberately invisible here. A process that is still
        starting and a process that is draining are both alive, and reporting either as
        dead is what turns a rolling deploy into a crash loop.
        """

        return await self._run(self._liveness)

    async def readiness(self) -> HealthReport:
        """Report whether this process should be sent traffic.

        Down until startup finishes, down again from the moment the process is asked to
        stop, and down whenever a dependency it needs in order to serve is down.
        """

        return await self._run(self._readiness)

    def _register(
        self, probe: dict[str, HealthIndicator], indicator: HealthIndicator, probe_name: str
    ) -> None:
        """Add one indicator to one probe, refusing a name that is already taken.

        The name is read once, here, so that a probe reports under the name the
        indicator had when it was registered, and an indicator that cannot say what it
        is called fails at registration rather than during a probe.
        """

        name = indicator.name
        if name in probe:
            raise ValueError(
                f"A {probe_name} indicator named {name!r} is already registered; a probe reports "
                "each name once, so two indicators cannot share one"
            )
        probe[name] = indicator

    async def _run(self, probe: Mapping[str, HealthIndicator]) -> HealthReport:
        """Check every indicator of one probe and aggregate the results into a report.

        The checks run together rather than one after another, so the timeout bounds the
        probe rather than each check in turn: a probe of ten indicators answers in the
        time of the slowest, not the sum, and stays inside the interval it is read on.
        Results keep registration order however they finish, because the order a report
        is read in must not depend on which dependency happened to be slow.
        """

        names = tuple(probe)
        results = await asyncio.gather(*(self._check(name, probe[name]) for name in names))
        checks = dict(zip(names, results, strict=True))
        failed = any(result.status is HealthStatus.DOWN for result in checks.values())
        return HealthReport(
            status=HealthStatus.DOWN if failed else HealthStatus.UP,
            checks=MappingProxyType(checks),
        )

    async def _check(self, name: str, indicator: HealthIndicator) -> HealthIndicatorResult:
        """Run one indicator, turning any way it can fail into a down result.

        Cancellation is not a failure of the indicator and is left to propagate, so a
        probe whose caller went away stops rather than reporting on a check it abandoned.
        """

        try:
            async with asyncio.timeout(self._check_timeout):
                result = await indicator.check()
        except TimeoutError:
            self._logger.error(
                f"Health indicator {name!r} did not answer within {self._check_timeout} seconds"
            )
            return HealthIndicatorResult.down("the check did not answer in time")
        except Exception as exc:
            self._logger.error(f"Health indicator {name!r} raised {type(exc).__name__}: {exc}")
            return HealthIndicatorResult.down("the check failed")

        if not isinstance(result, HealthIndicatorResult):
            self._logger.error(
                f"Health indicator {name!r} answered with {type(result).__name__} rather than a "
                "health indicator result"
            )
            return HealthIndicatorResult.down("the check answered with an unusable result")
        return result


__all__ = (
    "DEFAULT_CHECK_TIMEOUT",
    "HealthService",
)
