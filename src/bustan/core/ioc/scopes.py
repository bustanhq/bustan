"""Scope management and instance caching for the IoC container."""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Hashable, MutableMapping
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar, Token
from typing import TYPE_CHECKING, Any, Final, Protocol, cast, runtime_checkable

import anyio
from starlette.requests import Request

from ..module.dynamic import ModuleKey

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Iterator
    from contextlib import AbstractAsyncContextManager, AbstractContextManager

REQUEST_SCOPE_CACHE_ATTR = "bustan_request_provider_cache"
REQUEST_SCOPE_CONTROLLER_CACHE_ATTR = "bustan_request_controller_cache"

DurableKey = tuple[ModuleKey, object, Hashable]

# A durable instance is cached under a key its provider derives from the request, so
# whoever supplies that input decides how many partitions exist. The store is bounded
# for that reason: an unauthenticated caller varying one header would otherwise grow
# the process until it runs out of memory.
DURABLE_INSTANCE_LIMIT: Final = 128


class _CacheMiss:
    """The type of the one object standing for 'nothing is cached here'."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "CACHE_MISS"


# What a cache getter returns when it holds no instance. ``None`` cannot serve as
# that answer: a provider may legitimately produce ``None``, and a probe that reads
# the absence of a value out of it rebuilds that provider on every resolution.
CACHE_MISS: Final = _CacheMiss()


class BoundedInstanceStore(MutableMapping[Any, object]):
    """A cache of at most ``limit`` instances, dropping the least recently used.

    Reading an entry counts as a use and so does writing one, so the entry dropped
    when the store is full is whichever has gone longest without either. Every
    operation is taken under one lock, because the store is written from whichever
    threads happen to be serving requests.
    """

    __slots__ = ("_entries", "_guard", "limit")

    def __init__(self, limit: int) -> None:
        if limit < 1:
            raise ValueError(f"an instance store must be allowed at least one entry, not {limit}")
        self.limit = limit
        self._entries: OrderedDict[Any, object] = OrderedDict()
        self._guard = threading.Lock()

    def __getitem__(self, key: Any) -> object:
        with self._guard:
            instance = self._entries[key]
            self._entries.move_to_end(key)
            return instance

    def __setitem__(self, key: Any, instance: object) -> None:
        with self._guard:
            self._entries[key] = instance
            self._entries.move_to_end(key)
            while len(self._entries) > self.limit:
                self._entries.popitem(last=False)

    def __delitem__(self, key: Any) -> None:
        with self._guard:
            del self._entries[key]

    def __iter__(self) -> Iterator[Any]:
        # A snapshot, because a caller reading the store one key at a time is
        # otherwise walking a table another thread's eviction resizes underneath it.
        with self._guard:
            return iter(tuple(self._entries))

    def __len__(self) -> int:
        return len(self._entries)


class _LockEntry[LockT]:
    """One cache key's construction lock and the resolutions holding or awaiting it."""

    __slots__ = ("holders", "lock")

    def __init__(self, lock: LockT) -> None:
        self.lock = lock
        self.holders = 0


class ConstructionLocks[LockT]:
    """The construction locks in flight, one entry per instance being built.

    An entry lives only as long as some resolution holds its lock or waits for it, so
    the table measures work in flight rather than every key ever constructed and a
    caller varying the input a durable key is derived from cannot grow it.

    Holders are counted rather than an entry being deleted on release: a waiter has
    already taken the entry it is blocked on, and deleting that entry would let the
    next caller create a second lock for the same key, leaving the two to construct
    the same instance at the same time. The last holder out removes the entry.
    """

    __slots__ = ("_entries", "_guard", "_new_lock")

    def __init__(self, new_lock: Callable[[], LockT]) -> None:
        self._new_lock = new_lock
        self._entries: dict[object, _LockEntry[LockT]] = {}
        self._guard = threading.Lock()

    def __len__(self) -> int:
        return len(self._entries)

    def borrow(self, key: object) -> _LockEntry[LockT]:
        """Return a key's entry, counting the caller among those holding it."""

        with self._guard:
            entry = self._entries.get(key)
            if entry is None:
                entry = _LockEntry(self._new_lock())
                self._entries[key] = entry
            entry.holders += 1
            return entry

    def release(self, key: object, entry: _LockEntry[LockT]) -> None:
        """Drop the caller from an entry's holders, forgetting an entry nobody holds."""

        with self._guard:
            entry.holders -= 1
            if entry.holders <= 0 and self._entries.get(key) is entry:
                del self._entries[key]


@contextmanager
def _held(locks: ConstructionLocks[threading.Lock], key: object) -> Iterator[None]:
    """Hold one key's construction lock, giving the entry back on the way out."""

    entry = locks.borrow(key)
    try:
        with entry.lock:
            yield
    finally:
        locks.release(key, entry)


@asynccontextmanager
async def _held_async(locks: ConstructionLocks[anyio.Lock], key: object) -> AsyncIterator[None]:
    """Hold one key's awaited construction lock, giving the entry back on the way out."""

    entry = locks.borrow(key)
    try:
        async with entry.lock:
            yield
    finally:
        locks.release(key, entry)


@runtime_checkable
class DurableProvider(Protocol):
    """Protocol for providers that derive a durable cache key from the request."""

    @classmethod
    def get_durable_context_key(cls, request: Request | None) -> Hashable: ...


class ScopeManager:
    """Manages singleton and request-scoped instance lifetimes."""

    def __init__(self, *, durable_instance_limit: int = DURABLE_INSTANCE_LIMIT) -> None:
        self.singletons: dict[tuple[ModuleKey, object], object] = {}
        self.controller_singletons: dict[tuple[ModuleKey, type[object]], object] = {}
        self.controller_singleton_locks: dict[tuple[ModuleKey, type[object]], threading.Lock] = {}
        self.durable_instances = BoundedInstanceStore(durable_instance_limit)
        self.construction_locks: ConstructionLocks[threading.Lock] = ConstructionLocks(
            threading.Lock
        )
        self.async_construction_locks: ConstructionLocks[anyio.Lock] = ConstructionLocks(anyio.Lock)
        self._lock_table_guard = threading.Lock()
        self.active_request: ContextVar[Request | None] = ContextVar(
            "bustan_active_request", default=None
        )
        self.active_response: ContextVar[object | None] = ContextVar(
            "bustan_active_response", default=None
        )
        self.active_application: ContextVar[object | None] = ContextVar(
            "bustan_active_application", default=None
        )

    def get_singleton(self, key: tuple[ModuleKey, object]) -> object:
        """Return the cached process-wide instance, or ``CACHE_MISS`` when there is none."""

        return self.singletons.get(key, CACHE_MISS)

    def set_singleton(self, key: tuple[ModuleKey, object], instance: object) -> None:
        self.singletons[key] = instance

    def get_controller_singleton(self, key: tuple[ModuleKey, type[object]]) -> object | None:
        return self.controller_singletons.get(key)

    def set_controller_singleton(
        self, key: tuple[ModuleKey, type[object]], instance: object
    ) -> None:
        self.controller_singletons[key] = instance

    def get_controller_singleton_lock(self, key: tuple[ModuleKey, type[object]]) -> threading.Lock:
        try:
            return self.controller_singleton_locks[key]
        except KeyError:
            with self._lock_table_guard:
                return self.controller_singleton_locks.setdefault(key, threading.Lock())

    def get_durable(self, key: DurableKey) -> object:
        """Return the cached instance for a durable partition, or ``CACHE_MISS``."""

        return self.durable_instances.get(key, CACHE_MISS)

    def set_durable(self, key: DurableKey, instance: object) -> None:
        """Cache a durable instance, evicting the partition used longest ago when full."""

        self.durable_instances[key] = instance

    def get_construction_lock(self, key: object) -> AbstractContextManager[None]:
        """Return a guard holding the lock that serializes construction under one key."""

        return _held(self.construction_locks, key)

    def get_async_construction_lock(self, key: object) -> AbstractAsyncContextManager[None]:
        """Return a guard holding the lock that serializes awaited construction under one key.

        A threading lock held across an await would block the whole event loop, so the
        two drivers serialize on locks of different kinds under the same cache key.
        """

        return _held_async(self.async_construction_locks, key)

    def push_request(self, request: Request | None) -> Token[Request | None] | None:
        if request is None:
            return None
        return self.active_request.set(request)

    def pop_request(self, token: Token[Request | None] | None) -> None:
        if token is not None:
            self.active_request.reset(token)

    def push_response(self, response: object | None) -> Token[object | None] | None:
        if response is None:
            return None
        return self.active_response.set(response)

    def pop_response(self, token: Token[object | None] | None) -> None:
        if token is not None:
            self.active_response.reset(token)

    def push_application(self, application: object | None) -> Token[object | None] | None:
        if application is None:
            return None
        return self.active_application.set(application)

    def pop_application(self, token: Token[object | None] | None) -> None:
        if token is not None:
            self.active_application.reset(token)

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

    def clear_request_state(self, request: Request | None) -> None:
        if request is None:
            return

        state = getattr(request, "state", None)
        if state is None:
            return

        for attribute in (REQUEST_SCOPE_CACHE_ATTR, REQUEST_SCOPE_CONTROLLER_CACHE_ATTR):
            if hasattr(state, attribute):
                delattr(state, attribute)

    def clear_controller_singletons(self) -> None:
        """Drop cached singleton controller instances."""
        self.controller_singletons.clear()
