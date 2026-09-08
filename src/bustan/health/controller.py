"""The HTTP surface of the two probes."""

from __future__ import annotations

from ..common.decorators.controller import Controller
from ..common.decorators.route import Get
from ..contracts import HttpResponse
from ..security.throttler import SkipThrottle
from .indicators import HealthReport, HealthStatus
from .service import HealthService

# What a probe reader acts on is the status code, not the body: it is the only part a
# load balancer or a kubelet reads before deciding. The body says which check decided.
HEALTHY_STATUS_CODE = 200
UNHEALTHY_STATUS_CODE = 503


@Controller("health")
class HealthController:
    """Serves liveness at ``/health/live`` and readiness at ``/health/ready``.

    Both routes are exempt from throttling, because a probe is refused the moment it is
    counted with ordinary traffic: a rate-limited probe reports a process that is
    serving perfectly well as failed, and the process is then restarted or taken out of
    rotation for the load someone else put on it.

    They are not exempt from any guard the application installs globally. An application
    that authenticates every request must exclude these two routes itself, because only
    it knows what its own guards read; a probe that is answered with a rejection is a
    probe that fails permanently.
    """

    def __init__(self, health: HealthService) -> None:
        self._health = health

    @Get("live")
    @SkipThrottle
    async def live(self) -> HttpResponse:
        """Report whether the process is alive."""

        return _respond(await self._health.liveness())

    @Get("ready")
    @SkipThrottle
    async def ready(self) -> HttpResponse:
        """Report whether this process should be sent traffic."""

        return _respond(await self._health.readiness())


def _respond(report: HealthReport) -> HttpResponse:
    """Serialise a report, with the status code that carries its verdict."""

    healthy = report.status is HealthStatus.UP
    return HttpResponse.json(
        report.as_dict(),
        status_code=HEALTHY_STATUS_CODE if healthy else UNHEALTHY_STATUS_CODE,
        # A probe response describes this instant and nothing else, so nothing between
        # here and the reader may answer the next probe out of a cache.
        headers={"cache-control": "no-store"},
    )


__all__ = ("HealthController",)
