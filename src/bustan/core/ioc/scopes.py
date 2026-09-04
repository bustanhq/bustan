"""Scope management and instance caching for the IoC container."""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Hashable, Protocol, cast, runtime_checkable

from starlette.requests import Request

from ..module.dynamic import ModuleKey
from ...common.types import ProviderScope

REQUEST_SCOPE_CACHE_ATTR = "bustan_request_provider_cache"
REQUEST_SCOPE_CONTROLLER_CACHE_ATTR = "bustan_request_controller_cache"

DurableKey = tuple[ModuleKey, object, Hashable]

# The durable store is keyed by whatever a provider derives from the request, so
# a caller who varies that input decides how many entries exist. The store is
# therefore bounded and evicts least-recently-used partitions rather than
# growing until the process runs out of memory.
DURABLE_INSTANCE_LIMIT = 128

# How wide a context each scope caches over. An instance may only hold
# dependencies cached over a context at least as wide as its own; holding a
# narrower one means state belonging to a single caller outlives that caller and
# is served to the next. TRANSIENT keeps no cache of its own, so it inherits the
# context of whoever holds it and constrains nothing here.
_CONTEXT_WIDTH: dict[ProviderScope, int] = {
    ProviderScope.TRANSIENT: 0,
    ProviderScope.REQUEST: 1,
    ProviderScope.DURABLE: 2,
    ProviderScope.SINGLETON: 3,
}


def is_wider_scope(candidate: ProviderScope, baseline: ProviderScope) -> bool:
    """Return whether a scope caches over a wider context than another one."""

    return _CONTEXT_WIDTH[candidate] > _CONTEXT_WIDTH[baseline]


def dependency_escapes_owner(
    owner_scope: ProviderScope, dependency_scope: ProviderScope
) -> bool:
    """Return whether an owner would outlive a dependency it is about to hold.

    An owner cached over a wide context that holds a narrowly cached dependency
    keeps the first caller's state and serves it to every later caller, so such
    a pairing is refused. A transient owner or a transient dependency has no
    cache of its own and is never in itself unsafe.
    """

    if owner_scope is ProviderScope.TRANSIENT or dependency_scope is ProviderScope.TRANSIENT:
        return False
    return is_wider_scope(owner_scope, dependency_scope)


@dataclass(slots=True)
class _DurableConstructionLock:
    """A durable partition's construction lock and the resolutions holding it."""

    lock: threading.Lock = field(default_factory=threading.Lock)
    holders: int = 0


@runtime_checkable
class DurableProvider(Protocol):
    """Protocol for providers that derive a durable cache key from the request."""

    @classmethod
    def get_durable_context_key(cls, request: Request | None) -> Hashable: ...


class ScopeManager:
    """Manages singleton and request-scoped instance lifetimes."""

    def __init__(self, *, durable_instance_limit: int = DURABLE_INSTANCE_LIMIT) -> None:
        if durable_instance_limit < 1:
            raise ValueError("durable_instance_limit must be at least 1")
        self.singletons: dict[tuple[ModuleKey, object], object] = {}
        self.singleton_locks: dict[tuple[ModuleKey, object], threading.Lock] = {}
        self.controller_singletons: dict[tuple[ModuleKey, type[object]], object] = {}
        self.controller_singleton_locks: dict[
            tuple[ModuleKey, type[object]], threading.Lock
        ] = {}
        self.durable_instance_limit = durable_instance_limit
        self.durable_instances: OrderedDict[DurableKey, object] = OrderedDict()
        self.durable_locks: dict[DurableKey, _DurableConstructionLock] = {}
        self._singleton_locks_guard = threading.Lock()
        self._durable_guard = threading.Lock()
        self.active_request: ContextVar[Request | None] = ContextVar(
            "bustan_active_request", default=None
        )

    def get_singleton(self, key: tuple[ModuleKey, object]) -> object | None:
        return self.singletons.get(key)

    def set_singleton(self, key: tuple[ModuleKey, object], instance: object) -> None:
        self.singletons[key] = instance

    def get_singleton_lock(self, key: tuple[ModuleKey, object]) -> threading.Lock:
        try:
            return self.singleton_locks[key]
        except KeyError:
            with self._singleton_locks_guard:
                return self.singleton_locks.setdefault(key, threading.Lock())

    def get_controller_singleton(self, key: tuple[ModuleKey, type[object]]) -> object | None:
        return self.controller_singletons.get(key)

    def set_controller_singleton(
        self, key: tuple[ModuleKey, type[object]], instance: object
    ) -> None:
        self.controller_singletons[key] = instance

    def get_controller_singleton_lock(
        self, key: tuple[ModuleKey, type[object]]
    ) -> threading.Lock:
        try:
            return self.controller_singleton_locks[key]
        except KeyError:
            with self._singleton_locks_guard:
                return self.controller_singleton_locks.setdefault(key, threading.Lock())

    def get_durable(self, key: DurableKey) -> object | None:
        with self._durable_guard:
            instance = self.durable_instances.get(key)
            if instance is not None:
                self.durable_instances.move_to_end(key)
            return instance

    def set_durable(self, key: DurableKey, instance: object) -> None:
        """Cache a durable instance, evicting the least recently used partition.

        The number of partitions is chosen by whoever supplies the input the key
        is derived from, so the store never holds more than its limit.
        """
        with self._durable_guard:
            self.durable_instances[key] = instance
            self.durable_instances.move_to_end(key)
            while len(self.durable_instances) > self.durable_instance_limit:
                self.durable_instances.popitem(last=False)

    @contextmanager
    def durable_construction_lock(self, key: DurableKey) -> Iterator[None]:
        """Hold one durable partition's construction lock for the caller.

        The lock exists only for the construction it guards: its entry is
        dropped once the last resolution holding it has left, so the lock table
        cannot outgrow the work in flight.
        """
        with self._durable_guard:
            entry = self.durable_locks.get(key)
            if entry is None:
                entry = _DurableConstructionLock()
                self.durable_locks[key] = entry
            entry.holders += 1

        try:
            with entry.lock:
                yield
        finally:
            with self._durable_guard:
                entry.holders -= 1
                if entry.holders <= 0 and self.durable_locks.get(key) is entry:
                    del self.durable_locks[key]

    def push_request(self, request: Request | None) -> Token[Request | None] | None:
        if request is None:
            return None
        return self.active_request.set(request)

    def pop_request(self, token: Token[Request | None] | None) -> None:
        if token is not None:
            self.active_request.reset(token)

    def get_request_cache(self, request: Request) -> dict[tuple[ModuleKey, object], object]:
        """Return the instance cache associated with the current request."""
        request_scope_cache = getattr(request.state, REQUEST_SCOPE_CACHE_ATTR, None)
        if request_scope_cache is None:
            request_scope_cache = {}
            setattr(request.state, REQUEST_SCOPE_CACHE_ATTR, request_scope_cache)
        return cast(dict[tuple[ModuleKey, object], object], request_scope_cache)

    def get_request_controller_cache(
        self, request: Request
    ) -> dict[tuple[ModuleKey, type[object]], object]:
        """Return the controller cache associated with the current request."""
        request_scope_cache = getattr(request.state, REQUEST_SCOPE_CONTROLLER_CACHE_ATTR, None)
        if request_scope_cache is None:
            request_scope_cache = {}
            setattr(request.state, REQUEST_SCOPE_CONTROLLER_CACHE_ATTR, request_scope_cache)
        return cast(dict[tuple[ModuleKey, type[object]], object], request_scope_cache)

    def clear_controller_singletons(self) -> None:
        """Drop cached singleton controller instances."""
        self.controller_singletons.clear()
