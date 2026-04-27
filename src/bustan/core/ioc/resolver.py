"""Recursive dependency resolution and constructor injection kernel."""

from __future__ import annotations

import inspect
import sys
from collections.abc import Callable
from contextvars import ContextVar
from typing import TypeVar, cast, get_type_hints

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response

from ..errors import ProviderResolutionError
from ..module.dynamic import ModuleKey
from ..utils import _display_name, _qualname
from ...common.types import ProviderScope
from .overrides import OverrideManager
from .registry import Binding, Registry
from .scopes import ScopeManager

ResolvedT = TypeVar("ResolvedT")
FRAMEWORK_OWNED_TYPES = frozenset({Request, Response, Starlette})


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
                active_req = self.scope_manager.active_request.get()
                durable_key = self._get_durable_context_key(binding, active_req)
                durable_cache_key = (declaring_module, token, durable_key)
                lock = self.scope_manager.get_durable_lock(durable_cache_key)
                with lock:
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
                cls_target, module=module_key, request=self.scope_manager.active_request.get()
            )
        elif binding.resolver_kind == "factory":
            factory, inject_tokens = binding.target  # type: ignore
            return self.call_factory(
                factory, inject_tokens, module=module_key, request=self.scope_manager.active_request.get()
            )
        else:
            raise ProviderResolutionError(f"Unknown resolver kind: {binding.resolver_kind}")

    def instantiate_class(
        self,
        cls: type[object],
        *,
        module: ModuleKey,
        request: Request | None = None,
    ) -> object:
        """Resolve a fresh controller or class instance for request handling."""

        active_request_token = self.scope_manager.push_request(request)
        try:
            positional_arguments, keyword_arguments = self._resolve_constructor_dependencies(
                cls, module
            )
            return cls(*positional_arguments, **keyword_arguments)
        finally:
            self.scope_manager.pop_request(active_request_token)

    def call_factory(
        self,
        factory: Callable[..., object],
        inject: tuple[object, ...],
        *,
        module: ModuleKey,
        request: Request | None = None,
    ) -> object:
        """Resolve parameters using inject mapping and calls the factory."""

        active_request_token = self.scope_manager.push_request(request)
        try:
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

    def _resolve_constructor_dependencies(
        self,
        class_cls: type[object],
        module_key: ModuleKey,
    ) -> tuple[tuple[object, ...], dict[str, object]]:

        owner_is_controller = class_cls in self.registry.controller_modules
        is_request_scoped = False
        is_durable_scoped = False

        for binding in self.registry.bindings.values():
            if binding.resolver_kind == "class" and binding.target is class_cls:
                if binding.scope is ProviderScope.REQUEST:
                    is_request_scoped = True
                elif binding.scope is ProviderScope.DURABLE:
                    is_durable_scoped = True
                break

        constructor = class_cls.__init__
        if constructor is object.__init__:
            return (), {}

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

            if annotation in FRAMEWORK_OWNED_TYPES:
                if (
                    annotation is Request
                    and (is_request_scoped or is_durable_scoped or owner_is_controller)
                    and active_request is not None
                ):
                    if parameter.kind in (
                        inspect.Parameter.POSITIONAL_ONLY,
                        inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    ):
                        positional_arguments.append(active_request)
                    else:
                        keyword_arguments[parameter.name] = active_request
                    continue

                raise ProviderResolutionError(
                    f"{_qualname(class_cls)}.__init__ parameter {parameter.name!r} requests "
                    f"framework-owned type {annotation.__name__ if hasattr(annotation, '__name__') else annotation}, which is not available in provider DI"
                )

            if not isinstance(annotation, str):
                dependency_declaring_module = self.registry.module_visibility.get(module_key, {}).get(
                    annotation
                )
                if dependency_declaring_module is not None:
                    dependency_binding = self.registry.bindings.get(
                        (dependency_declaring_module, annotation)
                    )
                    if dependency_binding is not None:
                        if (
                            dependency_binding.scope is ProviderScope.REQUEST
                            and not is_request_scoped
                            and not owner_is_controller
                        ):
                            raise ProviderResolutionError(
                                f"{_qualname(class_cls)}.__init__ parameter {parameter.name!r} depends on "
                                f"request-scoped provider {_qualname(annotation)}, which can only be injected "
                                "into request-scoped providers or controllers"
                            )

            dependency = self.resolve(annotation, module=module_key, request=active_request)
            if parameter.kind in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            ):
                positional_arguments.append(dependency)
            else:
                keyword_arguments[parameter.name] = dependency

        return tuple(positional_arguments), keyword_arguments

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
    ) -> object:
        target = binding.target
        if isinstance(target, type) and hasattr(target, "get_durable_context_key"):
            return cast(
                object,
                getattr(target, "get_durable_context_key")(request),
            )
        if request is not None:
            return id(request)
        return "__default_durable_context__"
