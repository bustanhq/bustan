"""Simple throttling guard and dynamic module."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from ..common.decorators.injectable import Injectable
from ..core.ioc.tokens import APP_GUARD, InjectionToken
from ..core.module.decorators import Module
from ..core.module.dynamic import DynamicModule
from ..pipeline.context import ExecutionContext
from ..pipeline.guards import Guard
from ..pipeline.metadata import RateLimitPolicy, extend_handler_policy_metadata

THROTTLER_TTL = InjectionToken[int]("THROTTLER_TTL")
THROTTLER_LIMIT = InjectionToken[int]("THROTTLER_LIMIT")
THROTTLER_STORAGE = InjectionToken["ThrottlerStorage"]("THROTTLER_STORAGE")
SKIP_THROTTLE_ATTR = "__bustan_skip_throttle__"


@runtime_checkable
class ThrottlerStorage(Protocol):
    """Protocol for request counting backends."""

    def increment(self, key: str, ttl: int) -> int: ...

    def get_ttl(self, key: str) -> int: ...


@dataclass
class InMemoryThrottlerStorage:
    """In-memory fixed-window throttling storage."""

    _windows: dict[str, tuple[float, int, int]] = field(default_factory=dict, init=False)

    def increment(self, key: str, ttl: int) -> int:
        now = time.monotonic()
        started_at, count, existing_ttl = self._windows.get(key, (now, 0, ttl))
        if now - started_at >= existing_ttl:
            started_at, count, existing_ttl = now, 0, ttl
        count += 1
        self._windows[key] = (started_at, count, ttl)
        return count

    def get_ttl(self, key: str) -> int:
        now = time.monotonic()
        started_at, _count, ttl = self._windows.get(key, (now, 0, 0))
        remaining = max(0, ttl - int(now - started_at))
        return remaining


def SkipThrottle(handler):
    """Mark a route handler as exempt from throttling."""
    setattr(handler, SKIP_THROTTLE_ATTR, True)
    extend_handler_policy_metadata(handler, rate_limit=RateLimitPolicy(skip=True))
    return handler


@Injectable
class ThrottlerGuard(Guard):
    """Guard that rejects requests after the configured limit is exceeded."""

    def __init__(self, storage: ThrottlerStorage, ttl: int, limit: int) -> None:
        self.storage = storage
        self.ttl = ttl
        self.limit = limit

    async def can_activate(self, context: ExecutionContext) -> bool:
        route = context.route
        request = context.request
        assert route is not None
        assert request is not None

        policy_plan = context.get_policy_plan()
        if getattr(getattr(policy_plan, "rate_limit", None), "skip", False):
            return True
        if getattr(route.handler, SKIP_THROTTLE_ATTR, False):
            return True

        client = request.client
        key = f"throttle:{client.host if client is not None else 'unknown'}"
        count = self.storage.increment(key, self.ttl)
        request.state.rate_limit_limit = self.limit
        request.state.rate_limit_remaining = max(0, self.limit - count)
        request.state.rate_limit_reset = self.storage.get_ttl(key)
        request.state.rate_limit_exceeded = count > self.limit
        return count <= self.limit


@Module()
class _ThrottlerModuleBase:
    pass


class ThrottlerModule:
    """Factory for throttling support."""

    @staticmethod
    def for_root(*, ttl: int, limit: int) -> DynamicModule:
        return DynamicModule(
            module=_ThrottlerModuleBase,
            providers=(
                {"provide": THROTTLER_TTL, "use_value": ttl},
                {"provide": THROTTLER_LIMIT, "use_value": limit},
                {"provide": THROTTLER_STORAGE, "use_class": InMemoryThrottlerStorage},
                {
                    "provide": ThrottlerGuard,
                    "use_factory": lambda storage, configured_ttl, configured_limit: ThrottlerGuard(
                        storage, configured_ttl, configured_limit
                    ),
                    "inject": (THROTTLER_STORAGE, THROTTLER_TTL, THROTTLER_LIMIT),
                },
                {"provide": APP_GUARD, "use_existing": ThrottlerGuard},
            ),
            exports=(ThrottlerGuard, THROTTLER_STORAGE),
        )
