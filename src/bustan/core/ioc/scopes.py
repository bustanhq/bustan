"""Scope management and instance caching for the IoC container."""

from __future__ import annotations

import threading
from contextvars import ContextVar, Token
from typing import Hashable, Protocol, cast, runtime_checkable

from starlette.requests import Request

from ..module.dynamic import ModuleKey

REQUEST_SCOPE_CACHE_ATTR = "bustan_request_provider_cache"
REQUEST_SCOPE_CONTROLLER_CACHE_ATTR = "bustan_request_controller_cache"


@runtime_checkable
class DurableProvider(Protocol):
    """Protocol for providers that derive a durable cache key from the request."""

    @classmethod
    def get_durable_context_key(cls, request: Request | None) -> Hashable: ...


class ScopeManager:
    """Manages singleton and request-scoped instance lifetimes."""

    def __init__(self) -> None:
        self.singletons: dict[tuple[ModuleKey, object], object] = {}
        self.singleton_locks: dict[tuple[ModuleKey, object], threading.Lock] = {}
        self.controller_singletons: dict[tuple[ModuleKey, type[object]], object] = {}
        self.controller_singleton_locks: dict[
            tuple[ModuleKey, type[object]], threading.Lock
        ] = {}
        self.durable_instances: dict[tuple[ModuleKey, object, Hashable], object] = {}
        self.durable_locks: dict[tuple[ModuleKey, object, Hashable], threading.Lock] = {}
        self._singleton_locks_guard = threading.Lock()
        self.active_request: ContextVar[Request | None] = ContextVar(
            "bustan_active_request", default=None
        )
        self.active_response: ContextVar[object | None] = ContextVar(
            "bustan_active_response", default=None
        )
        self.active_application: ContextVar[object | None] = ContextVar(
            "bustan_active_application", default=None
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

    def get_durable(self, key: tuple[ModuleKey, object, Hashable]) -> object | None:
        return self.durable_instances.get(key)

    def set_durable(self, key: tuple[ModuleKey, object, Hashable], instance: object) -> None:
        self.durable_instances[key] = instance

    def get_durable_lock(self, key: tuple[ModuleKey, object, Hashable]) -> threading.Lock:
        try:
            return self.durable_locks[key]
        except KeyError:
            with self._singleton_locks_guard:
                return self.durable_locks.setdefault(key, threading.Lock())

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
