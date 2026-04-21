"""Scope management and instance caching for the IoC container."""

from __future__ import annotations

import threading
from contextvars import ContextVar, Token
from typing import cast

from starlette.requests import Request

from ..module.dynamic import ModuleKey

REQUEST_SCOPE_CACHE_ATTR = "bustan_request_provider_cache"


class ScopeManager:
    """Manages singleton and request-scoped instance lifetimes."""

    def __init__(self) -> None:
        self.singletons: dict[tuple[ModuleKey, object], object] = {}
        self.singleton_locks: dict[tuple[ModuleKey, object], threading.Lock] = {}
        self._singleton_locks_guard = threading.Lock()
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
