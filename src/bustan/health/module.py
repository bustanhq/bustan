"""The dynamic module that provides the probes and the state they read."""

from __future__ import annotations

from ..kernel.ioc.tokens import InjectionToken
from ..kernel.module.decorators import Module
from ..kernel.module.dynamic import DynamicModule
from .controller import HealthController
from .readiness import ReadinessState
from .service import DEFAULT_CHECK_TIMEOUT, HealthService

HEALTH_CHECK_TIMEOUT = InjectionToken[float]("HEALTH_CHECK_TIMEOUT")


@Module()
class _HealthModuleBase:
    pass


class HealthModule:
    """Factory for the health module: the probes, their routes, and the readiness state."""

    @staticmethod
    def for_root(
        *,
        check_timeout: float = DEFAULT_CHECK_TIMEOUT,
        is_global: bool = True,
    ) -> DynamicModule:
        """Register the probe routes and export the service and the readiness state.

        Global by default, because both of the things it exports are used from outside
        the module that declared them: an indicator is registered by whichever module
        owns the dependency it watches, and the readiness state is set by whatever owns
        the shutdown sequence.

        Register indicators by injecting ``HealthService`` and calling its register
        methods from a module initialization hook. That stage runs before any hook can
        report the application started, so an indicator registered there is already
        being consulted the first time readiness can be true.

        ``check_timeout`` is how long any one indicator is given to answer before it is
        recorded as down. Indicators are checked together, so it bounds the whole probe
        however many are registered; keep it below the interval the probe is read on.
        """

        return DynamicModule(
            module=_HealthModuleBase,
            providers=(
                ReadinessState,
                {"provide": HEALTH_CHECK_TIMEOUT, "use_value": check_timeout},
                {
                    "provide": HealthService,
                    "use_factory": _build_health_service,
                    "inject": (ReadinessState, HEALTH_CHECK_TIMEOUT),
                },
            ),
            controllers=(HealthController,),
            exports=(HealthService, ReadinessState),
            is_global=is_global,
        )


def _build_health_service(readiness_state: ReadinessState, check_timeout: float) -> HealthService:
    """Build the service over the readiness state the application also hands elsewhere."""

    return HealthService(readiness_state, check_timeout=check_timeout)


__all__ = (
    "HEALTH_CHECK_TIMEOUT",
    "HealthModule",
)
