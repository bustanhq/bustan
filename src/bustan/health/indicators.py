"""The unit a health probe is built from: one indicator, and the answer it gives."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class HealthStatus(StrEnum):
    """Whether one check, or a whole probe, is serving.

    Two values are the whole vocabulary because a probe is read by a machine that can
    only route traffic or withhold it, so any third state would have to be collapsed
    into one of these by whoever read it, and the collapse would be a guess. An
    indicator with more to say says it in its detail.
    """

    UP = "up"
    DOWN = "down"


@dataclass(frozen=True, slots=True)
class HealthIndicatorResult:
    """What one indicator answered, and why it answered that.

    ``detail`` is one short sentence for whoever reads the probe. It crosses a trust
    boundary, because anything that can reach the probe reads it, so it says what is
    wrong in the framework's own words and never carries a host name, a connection
    string, a credential, or the message of an exception raised inside a dependency.
    It is ``None`` on a serving result that has nothing to add.
    """

    status: HealthStatus
    detail: str | None = None

    @classmethod
    def up(cls, detail: str | None = None) -> HealthIndicatorResult:
        """Return a serving result, optionally saying something about it."""

        return cls(status=HealthStatus.UP, detail=detail)

    @classmethod
    def down(cls, detail: str) -> HealthIndicatorResult:
        """Return a failing result, which must say why it failed."""

        return cls(status=HealthStatus.DOWN, detail=detail)


class HealthIndicator(Protocol):
    """One question a probe asks about one dependency, and the name it answers under.

    An implementation watches exactly one thing, so that a probe reporting ``down``
    names which thing is down rather than only that something is. ``name`` is the key
    its result appears under in the report and must be unique within a probe.

    ``check`` is allowed to fail, in every way an ``await`` can fail: it may raise, and
    it may never return. Neither reaches the caller of the probe. A raise is recorded
    as a down result under this indicator's name, and an indicator that does not answer
    in time is recorded the same way, because a probe that one broken dependency can
    crash or hang is worse than no probe at all: it gets the process killed for a fault
    that was never the process's.
    """

    @property
    def name(self) -> str:
        """Key this indicator's result is reported under, unique within one probe."""

        raise NotImplementedError

    async def check(self) -> HealthIndicatorResult:
        """Answer for the one dependency this indicator watches."""

        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class HealthReport:
    """The answer one probe gives, and the wire shape it serialises to.

    ``status`` is ``up`` only when every entry in ``checks`` is up, so a probe with no
    indicators registered is up. ``checks`` keeps the order the indicators were
    registered in, and the built-in lifecycle check of the readiness probe comes first.

    ``as_dict`` renders the documented response shape, and is what an HTTP endpoint
    serialises. It is exactly two levels deep and has no optional keys: ``detail`` is
    always present and is ``null`` when the check had nothing to add, so a reader never
    has to tell a missing key from an absent detail::

        {
          "status": "down",
          "checks": {
            "lifecycle": {"status": "down", "detail": "startup has not completed"},
            "database": {"status": "up", "detail": null}
          }
        }

    The shape carries no timing, no version and no host name. Those identify the
    process to anything that can reach the probe, and none of them is needed to decide
    whether to send it traffic.
    """

    status: HealthStatus
    checks: Mapping[str, HealthIndicatorResult]

    def as_dict(self) -> dict[str, object]:
        """Render the documented response shape as plain JSON-serialisable data."""

        return {
            "status": self.status.value,
            "checks": {
                name: {"status": result.status.value, "detail": result.detail}
                for name, result in self.checks.items()
            },
        }


__all__ = (
    "HealthIndicator",
    "HealthIndicatorResult",
    "HealthReport",
    "HealthStatus",
)
