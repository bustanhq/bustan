"""Simple throttling guard and dynamic module."""

from __future__ import annotations

import time
from collections.abc import Callable
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
THROTTLER_KEY_RESOLVER = InjectionToken["ThrottlerKeyResolver"]("THROTTLER_KEY_RESOLVER")
SKIP_THROTTLE_ATTR = "__bustan_skip_throttle__"

ThrottlerKeyResolver = Callable[[ExecutionContext], str]


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

    def __init__(
        self,
        storage: ThrottlerStorage,
        ttl: int,
        limit: int,
        key_resolver: ThrottlerKeyResolver,
    ) -> None:
        self.storage = storage
        self.ttl = ttl
        self.limit = limit
        self.key_resolver = key_resolver

    async def can_activate(self, context: ExecutionContext) -> bool:
        request = context.request
        if request is None:
            raise RuntimeError("ThrottlerGuard requires an active HTTP request")

        policy_plan = context.get_policy_plan()
        if getattr(getattr(policy_plan, "rate_limit", None), "skip", False):
            return True

        handler = getattr(context.route, "handler", None)
        if handler is None:
            handler = getattr(context.get_handler(), "__func__", context.get_handler())
        if getattr(handler, SKIP_THROTTLE_ATTR, False):
            return True

        key = self.key_resolver(context)
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
    def for_root(
        *,
        ttl: int,
        limit: int,
        key_resolver: ThrottlerKeyResolver | None = None,
    ) -> DynamicModule:
        return DynamicModule(
            module=_ThrottlerModuleBase,
            providers=(
                {"provide": THROTTLER_TTL, "use_value": ttl},
                {"provide": THROTTLER_LIMIT, "use_value": limit},
                {"provide": THROTTLER_STORAGE, "use_class": InMemoryThrottlerStorage},
                {
                    "provide": THROTTLER_KEY_RESOLVER,
                    "use_value": key_resolver or _default_throttle_key,
                },
                {
                    "provide": ThrottlerGuard,
                    "use_factory": lambda storage, configured_ttl, configured_limit, configured_key_resolver: ThrottlerGuard(
                        storage,
                        configured_ttl,
                        configured_limit,
                        configured_key_resolver,
                    ),
                    "inject": (
                        THROTTLER_STORAGE,
                        THROTTLER_TTL,
                        THROTTLER_LIMIT,
                        THROTTLER_KEY_RESOLVER,
                    ),
                },
                {"provide": APP_GUARD, "use_existing": ThrottlerGuard},
            ),
            exports=(ThrottlerGuard, THROTTLER_STORAGE),
        )


def _default_throttle_key(context: ExecutionContext) -> str:
    request = context.request
    if request is None:
        return "throttle:unknown"

    client = request.client
    host = client.host if client is not None else "unknown"
    return f"throttle:{host}"
