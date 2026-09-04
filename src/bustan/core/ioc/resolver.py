"""Recursive dependency resolution and constructor injection kernel."""

from __future__ import annotations

import inspect
import sys
from collections.abc import Callable, Mapping
from contextvars import ContextVar
from typing import Hashable, TypeVar, cast, get_type_hints

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response

from ..errors import ProviderResolutionError
from ..module.dynamic import ModuleKey
from ..utils import _display_name, _qualname
from ...common.types import ProviderScope
from .overrides import OverrideManager
from .registry import Binding, Registry
from .scopes import (
    DurableKey,
    ScopeManager,
    dependency_escapes_owner,
    narrowest_scope,
)

ResolvedT = TypeVar("ResolvedT")
FRAMEWORK_OWNED_TYPES = frozenset({Request, Response, Starlette})


def _factory_label(factory: object) -> str:
    """Return a stable name for a factory to use in a diagnostic."""

    qualname = getattr(factory, "__qualname__", None)
    if qualname is None:
        return _qualname(factory)
    module = getattr(factory, "__module__", None)
    return f"{module}.{qualname}" if module else qualname


class Resolver:
    """Handles the recursive resolution of providers and classes."""

    def __init__(
        self,
        registry: Registry,
        scope_manager: ScopeManager,
        override_manager: OverrideManager,
    ) -> None:
        self.registry = registry
        self.scope_manager = scope_manager
        self.override_manager = override_manager
        self.resolution_stack: ContextVar[tuple[object, ...]] = ContextVar(
            "bustan_resolution_stack", default=()
        )
        self._graph_scopes_validated = False
        self._constructor_tokens: dict[tuple[type[object], ModuleKey], tuple[object, ...]] = {}

    def resolve(
        self,
        token: object,
        *,
        module: ModuleKey,
        request: Request | None = None,
    ) -> object:
        """Resolve a provider visible from the given module."""

        active_request_token = self.scope_manager.push_request(request)
        try:
            # Check for overrides before normal resolution
            if self.override_manager.has_override(token, module=module):
                return self.override_manager.get_override(token, module=module)

            declaring_module = self._get_declaring_module(token, module)
            binding_key = (declaring_module, token)

            # Note: Overrides are handled by the high-level Container for now, 
            # or we could move them here if Container delegates entirely.
            # For this Phase 2, we keep Resolver focused on the core algorithm.
            
            # This 'resolve' call is called by Container.resolve which handles overrides.
            # If called internally for dependencies, it should also handle overrides.
            # To avoid circularity in logic, Resolver will be told about overrides 
            # or the Container will be the one managing them.
            # Let's assume Container manages the high-level 'resolve' and Resolver 
            # handles the recursive 'binding' resolution.

            binding = self.registry.get_binding(binding_key)
            if binding is None:
                # This shouldn't happen if _get_declaring_module passed
                raise ProviderResolutionError(f"Binding not found for {token!r}")

            # The durable key is derived from the request by provider code, so it
            # is computed once per resolution and reused for the write-back.
            durable_cache_key: DurableKey | None = None

            if binding.scope is ProviderScope.REQUEST:
                active_req = self.scope_manager.active_request.get()
                if active_req is None:
                    raise ProviderResolutionError(
                        f"Request-scoped provider {_qualname(token)} requires an active request"
                    )
                request_cache = self.scope_manager.get_request_cache(active_req)
                if binding_key in request_cache:
                    return request_cache[binding_key]

            elif binding.scope is ProviderScope.DURABLE:
                active_req = self.scope_manager.active_request.get()
                durable_key = self._get_durable_context_key(binding, active_req)
                durable_cache_key = (declaring_module, token, durable_key)
                instance = self.scope_manager.get_durable(durable_cache_key)
                if instance is not None:
                    return instance

            elif binding.scope is ProviderScope.SINGLETON:
                instance = self.scope_manager.get_singleton(binding_key)
                if instance is not None:
                    return instance

            # Detect circular dependencies
            current_stack = self.resolution_stack.get()
            if token in current_stack:
                cycle_path = " -> ".join(
                    _display_name(dependency) for dependency in (*current_stack, token)
                )
                raise ProviderResolutionError(
                    f"Circular provider dependencies detected: {cycle_path}"
                )

            stack_token = self.resolution_stack.set((*current_stack, token))
            try:
                instance = self._resolve_binding(binding, module_key=declaring_module)
            finally:
                self.resolution_stack.reset(stack_token)

            if binding.scope is ProviderScope.REQUEST:
                active_req = self.scope_manager.active_request.get()
                assert active_req is not None
                request_cache = self.scope_manager.get_request_cache(active_req)
                request_cache[binding_key] = instance
            elif binding.scope is ProviderScope.DURABLE:
                assert durable_cache_key is not None
                with self.scope_manager.durable_construction_lock(durable_cache_key):
                    existing = self.scope_manager.get_durable(durable_cache_key)
                    if existing is None:
                        self.scope_manager.set_durable(durable_cache_key, instance)
                    else:
                        instance = existing
            elif binding.scope is ProviderScope.SINGLETON:
                lock = self.scope_manager.get_singleton_lock(binding_key)
                with lock:
                    existing = self.scope_manager.get_singleton(binding_key)
                    if existing is None:
                        self.scope_manager.set_singleton(binding_key, instance)
                    else:
                        instance = existing

            return instance
        finally:
            self.scope_manager.pop_request(active_request_token)

    def _resolve_binding(self, binding: Binding, module_key: ModuleKey) -> object:
        if binding.resolver_kind == "value":
            return binding.target
        elif binding.resolver_kind == "existing":
            return self.resolve(
                binding.target, module=module_key, request=self.scope_manager.active_request.get()
            )
        elif binding.resolver_kind == "class":
            cls_target = cast(type[object], binding.target)
            return self.instantiate_class(
                cls_target,
                module=module_key,
                request=self.scope_manager.active_request.get(),
                owner_scope=binding.scope,
            )
        elif binding.resolver_kind == "factory":
            factory, inject_tokens = binding.target  # type: ignore
            return self.call_factory(
                factory,
                inject_tokens,
                module=module_key,
                request=self.scope_manager.active_request.get(),
                owner_scope=binding.scope,
            )
        else:
            raise ProviderResolutionError(f"Unknown resolver kind: {binding.resolver_kind}")

    def instantiate_class(
        self,
        cls: type[object],
        *,
        module: ModuleKey,
        request: Request | None = None,
        owner_scope: ProviderScope | None = None,
    ) -> object:
        """Resolve a fresh controller or class instance for request handling.

        ``owner_scope`` is the lifetime the caller will cache the new instance
        under, and it is what every dependency is checked against. A caller that
        caches beyond the current request must pass it. When it is omitted the
        class's registered scope is used, and a class with no registration is
        assumed to live for the whole process, so anything shorter-lived is
        refused rather than silently captured.
        """

        active_request_token = self.scope_manager.push_request(request)
        try:
            effective_scope = (
                owner_scope if owner_scope is not None else self._registered_scope(cls)
            )
            positional_arguments, keyword_arguments = self._resolve_constructor_dependencies(
                cls, module, effective_scope
            )
            return cls(*positional_arguments, **keyword_arguments)
        finally:
            self.scope_manager.pop_request(active_request_token)

    def validate_graph_scopes(
        self, controller_scopes: Mapping[type[object], ProviderScope]
    ) -> None:
        """Refuse a graph in which an owner would capture shorter-lived state.

        Every class the graph can build is checked against the lifetime it will
        be cached under, so a graph that would serve one caller's state to the
        next is rejected while the application is being assembled rather than by
        the first request that happens to trip it. The check runs once; the
        graph does not change after assembly.
        """

        if self._graph_scopes_validated:
            return
        self._graph_scopes_validated = True

        for (module_key, _token), binding in self.registry.bindings.items():
            if binding.resolver_kind == "class" and isinstance(binding.target, type):
                self._check_constructor_scopes(binding.target, module_key, binding.scope)
            elif binding.resolver_kind == "factory":
                self._check_factory_scopes(binding, module_key)

        for controller_cls, module_key in self.registry.controller_modules.items():
            owner_scope = controller_scopes.get(controller_cls, ProviderScope.SINGLETON)
            self._check_constructor_scopes(controller_cls, module_key, owner_scope)

    def _registered_scope(self, class_cls: type[object]) -> ProviderScope:
        """Return the scope a class is registered under, widest when unknown."""

        for binding in self.registry.bindings.values():
            if binding.resolver_kind == "class" and binding.target is class_cls:
                return binding.scope
        return ProviderScope.SINGLETON

    def _check_constructor_scopes(
        self,
        class_cls: type[object],
        module_key: ModuleKey,
        owner_scope: ProviderScope,
    ) -> None:
        """Apply the scope guard to a constructor without building anything."""

        try:
            inspected = self._inspect_constructor(class_cls, module_key)
        except ProviderResolutionError:
            # A constructor that cannot be inspected is not a scope problem, and
            # resolution reports it with the context of the request that hit it.
            return
        if inspected is None:
            return

        signature, type_hints = inspected
        for parameter in signature.parameters.values():
            annotation = type_hints.get(parameter.name)
            if parameter.name == "self" or annotation is None:
                continue
            self._guard_dependency_scope(
                f"{_qualname(class_cls)}.__init__",
                f"parameter {parameter.name!r}",
                annotation,
                module_key,
                owner_scope,
            )

    def _check_factory_scopes(self, binding: Binding, module_key: ModuleKey) -> None:
        """Apply the scope guard to a factory's injected tokens."""

        factory, inject_tokens = cast(
            tuple[Callable[..., object], tuple[object, ...]], binding.target
        )
        for token in inject_tokens:
            self._guard_dependency_scope(
                f"Factory {_factory_label(factory)}",
                "inject entry",
                token,
                module_key,
                binding.scope,
            )

    def _locate_binding(
        self, token: object, module_key: ModuleKey
    ) -> tuple[Binding, ModuleKey] | None:
        """Return a token's binding and the module declaring it, if it has one."""

        try:
            declaring_module = self.registry.module_visibility.get(module_key, {}).get(token)
        except TypeError:
            # An unhashable annotation cannot be a provider token.
            return None
        if declaring_module is None:
            return None
        binding = self.registry.bindings.get((declaring_module, token))
        if binding is None:
            return None
        return binding, declaring_module

    def _effective_dependency_scope(
        self,
        token: object,
        module_key: ModuleKey,
        seen: tuple[object, ...] = (),
    ) -> ProviderScope:
        """Return the narrowest scope a dependency can hand to whoever holds it.

        A provider with a cache of its own hands over exactly that cache's
        scope. A transient has no cache and an alias has no instance of its own,
        so each hands over whatever it reaches; the guard must see through both,
        or a long-lived owner captures request-local state one hop removed.
        """

        if token is Request:
            return ProviderScope.REQUEST
        if any(previous is token for previous in seen):
            # A cycle is reported by the resolution stack, not by this walk.
            return ProviderScope.TRANSIENT

        located = self._locate_binding(token, module_key)
        if located is None:
            return ProviderScope.TRANSIENT

        binding, declaring_module = located
        if binding.resolver_kind == "existing":
            return self._effective_dependency_scope(
                binding.target, declaring_module, (*seen, token)
            )
        if binding.scope is not ProviderScope.TRANSIENT:
            return binding.scope
        return self._reachable_scope(binding, declaring_module, (*seen, token))

    def _reachable_scope(
        self,
        binding: Binding,
        module_key: ModuleKey,
        seen: tuple[object, ...],
    ) -> ProviderScope:
        """Return the narrowest scope reachable through a binding that caches nothing."""

        if binding.resolver_kind == "factory":
            _factory, tokens = cast(
                tuple[Callable[..., object], tuple[object, ...]], binding.target
            )
        elif binding.resolver_kind == "class" and isinstance(binding.target, type):
            tokens = self._constructor_dependency_tokens(binding.target, module_key)
        else:
            return ProviderScope.TRANSIENT

        return narrowest_scope(
            self._effective_dependency_scope(token, module_key, seen) for token in tokens
        )

    def _constructor_dependency_tokens(
        self, class_cls: type[object], module_key: ModuleKey
    ) -> tuple[object, ...]:
        """Return the annotations a class's constructor asks the container for."""

        cache_key = (class_cls, module_key)
        cached = self._constructor_tokens.get(cache_key)
        if cached is not None:
            return cached

        try:
            inspected = self._inspect_constructor(class_cls, module_key)
        except ProviderResolutionError:
            inspected = None

        tokens: tuple[object, ...] = ()
        if inspected is not None:
            signature, type_hints = inspected
            tokens = tuple(
                annotation
                for parameter in signature.parameters.values()
                if parameter.name != "self"
                and (annotation := type_hints.get(parameter.name)) is not None
            )

        self._constructor_tokens[cache_key] = tokens
        return tokens

    def _guard_dependency_scope(
        self,
        owner_label: str,
        dependency_label: str,
        annotation: object,
        module_key: ModuleKey,
        owner_scope: ProviderScope,
    ) -> None:
        """Refuse a dependency that lives for less time than the owner holding it."""

        if annotation is Request:
            if dependency_escapes_owner(owner_scope, ProviderScope.REQUEST):
                raise ProviderResolutionError(
                    f"{owner_label} {dependency_label} requests framework-owned type Request, "
                    "which is available only to request-scoped and transient owners. A "
                    f"{owner_scope.value}-scoped owner outlives the request and would serve the "
                    "first caller's request to every later caller"
                )
            return

        if isinstance(annotation, str) or annotation in FRAMEWORK_OWNED_TYPES:
            return

        located = self._locate_binding(annotation, module_key)
        if located is None:
            return

        binding, _declaring_module = located
        effective_scope = self._effective_dependency_scope(annotation, module_key)
        if not dependency_escapes_owner(owner_scope, effective_scope):
            return

        if binding.scope is effective_scope:
            raise ProviderResolutionError(
                f"{owner_label} {dependency_label} depends on {effective_scope.value}-scoped "
                f"provider {_qualname(annotation)}, which cannot be injected into a "
                f"{owner_scope.value}-scoped owner. The owner outlives the dependency and would "
                "share one caller's instance with the rest"
            )

        raise ProviderResolutionError(
            f"{owner_label} {dependency_label} depends on {_qualname(annotation)}, which reaches "
            f"{effective_scope.value}-scoped state and so cannot be injected into a "
            f"{owner_scope.value}-scoped owner. The owner would capture that state when it is "
            "first built and share it with every later caller"
        )

    def call_factory(
        self,
        factory: Callable[..., object],
        inject: tuple[object, ...],
        *,
        module: ModuleKey,
        request: Request | None = None,
        owner_scope: ProviderScope | None = None,
    ) -> object:
        """Resolve parameters using inject mapping and calls the factory.

        ``owner_scope`` is the lifetime the caller will cache the result under,
        and every injected token is checked against it. When it is omitted the
        widest lifetime is assumed, so anything shorter-lived is refused rather
        than captured by a result that outlives it.
        """

        active_request_token = self.scope_manager.push_request(request)
        try:
            effective_scope = (
                owner_scope if owner_scope is not None else ProviderScope.SINGLETON
            )
            for token in inject:
                self._guard_dependency_scope(
                    f"Factory {_factory_label(factory)}",
                    "inject entry",
                    token,
                    module,
                    effective_scope,
                )
            args = [self.resolve(t, module=module) for t in inject]
            return factory(*args)
        finally:
            self.scope_manager.pop_request(active_request_token)

    def _get_declaring_module(self, token: object, module_key: ModuleKey) -> ModuleKey:
        visibility = self.registry.module_visibility.get(module_key)
        if visibility is None:
            raise ProviderResolutionError(
                f"{_display_name(module_key)} is not part of the application container"
            )

        declaring_module = visibility.get(token)
        if declaring_module is None:
            raise ProviderResolutionError(
                f"{_qualname(token)} is not available to {_display_name(module_key)}. "
                "Dependencies must come from the same module or an imported module export"
            )
        return declaring_module

    def _inspect_constructor(
        self,
        class_cls: type[object],
        module_key: ModuleKey,
    ) -> tuple[inspect.Signature, dict[str, object]] | None:
        """Return a constructor's signature and resolved hints, or None if trivial."""

        constructor = class_cls.__init__
        if constructor is object.__init__:
            return None

        try:
            signature = inspect.signature(constructor)
        except (TypeError, ValueError) as exc:
            raise ProviderResolutionError(
                f"Could not inspect {_qualname(class_cls)}.__init__: {exc}"
            ) from exc

        try:
            type_hints = get_type_hints(
                constructor,
                globalns=getattr(
                    sys.modules.get(class_cls.__module__),
                    "__dict__",
                    constructor.__globals__,
                ),
                localns=self._build_type_hint_namespace(class_cls, module_key),
            )
        except (NameError, TypeError) as exc:
            raise ProviderResolutionError(
                f"Could not resolve type hints for {_qualname(class_cls)}.__init__: {exc}"
            ) from exc

        return signature, cast(dict[str, object], type_hints)

    def _resolve_constructor_dependencies(
        self,
        class_cls: type[object],
        module_key: ModuleKey,
        owner_scope: ProviderScope,
    ) -> tuple[tuple[object, ...], dict[str, object]]:

        inspected = self._inspect_constructor(class_cls, module_key)
        if inspected is None:
            return (), {}
        signature, type_hints = inspected

        positional_arguments: list[object] = []
        keyword_arguments: dict[str, object] = {}
        active_request = self.scope_manager.active_request.get()

        for parameter in signature.parameters.values():
            if parameter.name == "self":
                continue

            if parameter.kind in (
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            ):
                raise ProviderResolutionError(
                    f"{_qualname(class_cls)}.__init__ uses unsupported variadic parameter {parameter.name!r}"
                )

            annotation = type_hints.get(parameter.name)
            if annotation is None:
                raise ProviderResolutionError(
                    f"{_qualname(class_cls)}.__init__ parameter {parameter.name!r} is missing a type annotation"
                )

            self._guard_dependency_scope(
                f"{_qualname(class_cls)}.__init__",
                f"parameter {parameter.name!r}",
                annotation,
                module_key,
                owner_scope,
            )

            if annotation in FRAMEWORK_OWNED_TYPES:
                if annotation is Request and active_request is not None:
                    self._bind_argument(
                        parameter, active_request, positional_arguments, keyword_arguments
                    )
                    continue

                if annotation is Request:
                    raise ProviderResolutionError(
                        f"{_qualname(class_cls)}.__init__ parameter {parameter.name!r} requests "
                        "framework-owned type Request, which is only available while a request "
                        "is being handled"
                    )

                raise ProviderResolutionError(
                    f"{_qualname(class_cls)}.__init__ parameter {parameter.name!r} requests "
                    f"framework-owned type {annotation.__name__ if hasattr(annotation, '__name__') else annotation}, which is not available in provider DI"
                )

            dependency = self.resolve(annotation, module=module_key, request=active_request)
            self._bind_argument(parameter, dependency, positional_arguments, keyword_arguments)

        return tuple(positional_arguments), keyword_arguments

    @staticmethod
    def _bind_argument(
        parameter: inspect.Parameter,
        value: object,
        positional_arguments: list[object],
        keyword_arguments: dict[str, object],
    ) -> None:
        if parameter.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ):
            positional_arguments.append(value)
        else:
            keyword_arguments[parameter.name] = value

    def _build_type_hint_namespace(
        self,
        class_cls: type[object],
        module_key: ModuleKey,
    ) -> dict[str, object]:

        namespace: dict[str, object] = {
            class_cls.__name__: class_cls,
            Request.__name__: Request,
            Response.__name__: Response,
            Starlette.__name__: Starlette,
        }

        for controller_cls, mod in self.registry.controller_modules.items():
            if mod == module_key:
                namespace.setdefault(controller_cls.__name__, controller_cls)

        accessible_tokens = self.registry.module_visibility.get(module_key, {})
        for token in accessible_tokens:
            if isinstance(token, type):
                namespace.setdefault(token.__name__, token)

        return namespace

    def _get_durable_context_key(
        self,
        binding: Binding,
        request: Request | None,
    ) -> Hashable:
        target = binding.target
        if isinstance(target, type) and hasattr(target, "get_durable_context_key"):
            key = cast(object, getattr(target, "get_durable_context_key")(request))
            try:
                hash(key)
            except TypeError as exc:
                raise ProviderResolutionError(
                    f"{_qualname(binding.token)}.get_durable_context_key returned a "
                    f"{type(key).__name__}, which cannot be used as a cache key. "
                    "A durable context key must be hashable"
                ) from exc
            return key
        if request is not None:
            return id(request)
        return "__default_durable_context__"
