"""Dependency injection container assembly and runtime resolution."""

from __future__ import annotations

import inspect
import sys
import threading
from contextvars import ContextVar, Token
from collections.abc import Callable
from typing import TypeVar, cast, get_type_hints

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response

from .errors import InvalidControllerError, ProviderResolutionError
from .metadata import Binding, ProviderScope
from .module_graph import ModuleGraph
from .utils import _display_name, _qualname

ResolvedT = TypeVar("ResolvedT")
NO_OVERRIDE = object()
REQUEST_SCOPE_CACHE_ATTR = "bustan_request_provider_cache"

FRAMEWORK_OWNED_TYPES = frozenset({Request, Response, Starlette})


class Container:
    """Resolve providers and controllers against a validated module graph."""

    def __init__(self, module_graph: ModuleGraph) -> None:
        self.module_graph = module_graph
        self._bindings: dict[tuple[type[object], object], Binding] = {}
        self._module_visibility: dict[type[object], dict[object, type[object]]] = {}
        self._singletons: dict[tuple[type[object], object], object] = {}
        self._singleton_locks: dict[tuple[type[object], object], threading.Lock] = {}
        self._overrides: dict[tuple[type[object], object], object] = {}

        self._controller_modules: dict[type[object], type[object]] = {}

        self._resolution_stack: ContextVar[tuple[object, ...]] = ContextVar(
            "bustan_resolution_stack", default=()
        )
        self._active_request: ContextVar[Request | None] = ContextVar(
            "bustan_active_request", default=None
        )

        self._build_bindings()

    def _build_bindings(self) -> None:
        for node in self.module_graph.nodes:
            # Add all bindings to the registry
            for binding in node.bindings:
                self._bindings[(node.module, binding.token)] = binding
                if binding.scope is ProviderScope.SINGLETON:
                    self._singleton_locks[(node.module, binding.token)] = threading.Lock()

            # Providers are visible from their own module plus explicit exports
            # from directly imported modules. Everything else stays private.
            accessible_provider_modules: dict[object, type[object]] = {
                b.token: node.module for b in node.bindings
            }

            for imported_module in node.imports:
                for exported_token in self.module_graph.exports_for(imported_module):
                    existing_module = accessible_provider_modules.get(exported_token)
                    if existing_module is not None and existing_module is not node.module:
                        raise ProviderResolutionError(
                            f"{_qualname(node.module)} can access {_qualname(exported_token)} "
                            f"from both {_qualname(existing_module)} and {_qualname(imported_module)}"
                        )
                    accessible_provider_modules[exported_token] = imported_module

            self._module_visibility[node.module] = accessible_provider_modules

            for controller_cls in node.controllers:
                existing_module = self._controller_modules.get(controller_cls)
                if existing_module is not None and existing_module is not node.module:
                    raise InvalidControllerError(
                        f"{_qualname(controller_cls)} is declared in multiple modules: "
                        f"{_qualname(existing_module)} and {_qualname(node.module)}"
                    )
                self._controller_modules[controller_cls] = node.module

    def resolve(
        self,
        token: object,
        *,
        module: type[object],
        request: Request | None = None,
    ) -> object:
        """Resolve a provider visible from the given module.

        When a request is supplied, request-scoped providers are cached on that
        request so the same object instance is reused throughout the pipeline.
        """
        active_request_token = self._push_active_request(request)
        try:
            declaring_module = self._get_declaring_module(token, module)
            binding_key = (declaring_module, token)

            override_val = self._overrides.get(binding_key, NO_OVERRIDE)
            if override_val is not NO_OVERRIDE:
                return override_val

            binding = self._bindings[binding_key]

            if binding.scope is ProviderScope.REQUEST:
                active_req = self._active_request.get()
                if active_req is None:
                    raise ProviderResolutionError(
                        f"Request-scoped provider {_qualname(token)} requires an active request"
                    )
                request_cache = self._get_request_scope_cache(active_req)
                if binding_key in request_cache:
                    return request_cache[binding_key]

            elif binding.scope is ProviderScope.SINGLETON:
                if binding_key in self._singletons:
                    return self._singletons[binding_key]

            # Detect circular dependencies
            current_stack = self._resolution_stack.get()
            if token in current_stack:
                cycle_path = " -> ".join(
                    _display_name(dependency) for dependency in (*current_stack, token)
                )
                raise ProviderResolutionError(
                    f"Circular provider dependencies detected: {cycle_path}"
                )

            stack_token = self._resolution_stack.set((*current_stack, token))
            try:
                # We do resolution according to resolver_kind
                instance = self._resolve_binding(binding, module_cls=declaring_module)
            finally:
                self._resolution_stack.reset(stack_token)

            if binding.scope is ProviderScope.REQUEST:
                active_req = self._active_request.get()
                assert active_req is not None
                request_cache = self._get_request_scope_cache(active_req)
                request_cache[binding_key] = instance
            elif binding.scope is ProviderScope.SINGLETON:
                lock = self._singleton_locks[binding_key]
                with lock:
                    if binding_key not in self._singletons:
                        self._singletons[binding_key] = instance
                    instance = self._singletons[binding_key]

            return instance
        finally:
            self._reset_active_request(active_request_token)

    def _resolve_binding(self, binding: Binding, module_cls: type[object]) -> object:
        if binding.resolver_kind == "value":
            return binding.target
        elif binding.resolver_kind == "existing":
            # Delegate to existing token matching the bound target string/object.
            return self.resolve(
                binding.target, module=module_cls, request=self._active_request.get()
            )
        elif binding.resolver_kind == "class":
            cls_target = cast(type[object], binding.target)
            return self.instantiate_class(
                cls_target, module=module_cls, request=self._active_request.get()
            )
        elif binding.resolver_kind == "factory":
            factory, inject_tokens = binding.target  # type: ignore
            return self.call_factory(
                factory, inject_tokens, module=module_cls, request=self._active_request.get()
            )
        else:
            raise ProviderResolutionError(f"Unknown resolver kind: {binding.resolver_kind}")

    def instantiate_class(
        self,
        cls: type[object],
        *,
        module: type[object],
        request: Request | None = None,
    ) -> object:
        """Resolve a fresh controller or class instance for request handling."""

        active_request_token = self._push_active_request(request)
        try:
            positional_arguments, keyword_arguments = self._resolve_constructor_dependencies(
                cls, module
            )
            return cls(*positional_arguments, **keyword_arguments)
        finally:
            self._reset_active_request(active_request_token)

    def call_factory(
        self,
        factory: Callable[..., object],
        inject: tuple[object, ...],
        *,
        module: type[object],
        request: Request | None = None,
    ) -> object:
        """Resolve parameters using inject mapping and calls the factory."""

        active_request_token = self._push_active_request(request)
        try:
            args = [self.resolve(t, module=module) for t in inject]
            return factory(*args)
        finally:
            self._reset_active_request(active_request_token)

    def override(self, token: object, value: object, *, module: type[object] | None = None) -> None:
        """Register a replacement object for a provider."""
        override_key = self._resolve_override_key(token, module)
        self._overrides[override_key] = value

    def clear_override(self, token: object, *, module: type[object] | None = None) -> None:
        """Remove any override registered for a provider."""
        override_key = self._resolve_override_key(token, module)
        self._overrides.pop(override_key, None)

    def has_override(self, token: object, *, module: type[object] | None = None) -> bool:
        override_key = self._resolve_override_key(token, module)
        return override_key in self._overrides

    def get_override(self, token: object, *, module: type[object] | None = None) -> object:
        override_key = self._resolve_override_key(token, module)
        return self._overrides[override_key]

    def _get_declaring_module(self, token: object, module_cls: type[object]) -> type[object]:
        try:
            visibility = self._module_visibility[module_cls]
        except KeyError as exc:
            raise ProviderResolutionError(
                f"{_qualname(module_cls)} is not part of the application container"
            ) from exc

        declaring_module = visibility.get(token)
        if declaring_module is None:
            raise ProviderResolutionError(
                f"{_qualname(token)} is not available to {_qualname(module_cls)}. "
                "Dependencies must come from the same module or an imported module export"
            )
        return declaring_module

    def _resolve_constructor_dependencies(
        self,
        class_cls: type[object],
        module_cls: type[object],
    ) -> tuple[tuple[object, ...], dict[str, object]]:

        # Determine if we are a request-scoped entity parsing injection deps
        # (Since we lack a standalone metadata checking helper here, we rely on the context's cache checks loosely, but let's be accurate if possible)
        # Previously, owner was checked against _controller_modules and ProviderMetadata.
        owner_is_controller = class_cls in self._controller_modules
        is_request_scoped = False

        # Check if the class is actually registered as a binding to know its scope
        # (Sometimes its not registered directly, e.g. a Controller)
        for binding in self._bindings.values():
            if binding.resolver_kind == "class" and binding.target is class_cls:
                if binding.scope is ProviderScope.REQUEST:
                    is_request_scoped = True
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
                localns=self._build_type_hint_namespace(class_cls, module_cls),
            )
        except (NameError, TypeError) as exc:
            raise ProviderResolutionError(
                f"Could not resolve type hints for {_qualname(class_cls)}.__init__: {exc}"
            ) from exc

        positional_arguments: list[object] = []
        keyword_arguments: dict[str, object] = {}
        active_request = self._active_request.get()

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
                    and (is_request_scoped or owner_is_controller)
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

            # verify scope correctness
            if not isinstance(
                annotation, str
            ):  # basic check to bypass str types if evaluating to weird hints
                dependency_declaring_module = self._module_visibility.get(module_cls, {}).get(
                    annotation
                )
                if dependency_declaring_module is not None:
                    dependency_binding = self._bindings.get(
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

            dependency = self.resolve(annotation, module=module_cls, request=active_request)
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
        module_cls: type[object],
    ) -> dict[str, object]:

        namespace: dict[str, object] = {
            class_cls.__name__: class_cls,
            Request.__name__: Request,
            Response.__name__: Response,
            Starlette.__name__: Starlette,
        }

        # Provide controller class names for resolution context
        for controller_cls, mod in self._controller_modules.items():
            if mod is module_cls:
                namespace.setdefault(controller_cls.__name__, controller_cls)

        accessible_tokens = self._module_visibility.get(module_cls, {})
        for token in accessible_tokens:
            if isinstance(token, type):
                namespace.setdefault(token.__name__, token)

        return namespace

    def _push_active_request(
        self,
        request: Request | None,
    ) -> Token[Request | None] | None:
        if request is None:
            return None
        return self._active_request.set(request)

    def _reset_active_request(
        self,
        token: Token[Request | None] | None,
    ) -> None:
        if token is not None:
            self._active_request.reset(token)

    def _get_request_scope_cache(
        self,
        request: Request,
    ) -> dict[tuple[type[object], object], object]:
        request_scope_cache = getattr(request.state, REQUEST_SCOPE_CACHE_ATTR, None)
        if request_scope_cache is None:
            request_scope_cache = {}
            setattr(request.state, REQUEST_SCOPE_CACHE_ATTR, request_scope_cache)
        return cast(dict[tuple[type[object], object], object], request_scope_cache)

    def _resolve_override_key(
        self,
        token: object,
        module_cls: type[object] | None,
    ) -> tuple[type[object], object]:
        if module_cls is not None:
            override_key = (module_cls, token)
            if override_key not in self._bindings:
                raise ProviderResolutionError(
                    f"{_qualname(token)} is not registered in {_qualname(module_cls)}"
                )
            return override_key

        declaring_modules = [
            registered_module
            for registered_module, registered_token in self._bindings
            if registered_token is token
        ]

        if not declaring_modules:
            raise ProviderResolutionError(f"{_qualname(token)} is not registered in the container")

        if len(declaring_modules) > 1:
            module_names = ", ".join(
                _qualname(registered_module) for registered_module in declaring_modules
            )
            raise ProviderResolutionError(
                f"{_qualname(token)} is registered in multiple modules ({module_names}); "
                "specify module_cls when overriding it"
            )

        return declaring_modules[0], token


def build_container(module_graph: ModuleGraph) -> Container:
    """Build the runtime container for a validated module graph."""
    return Container(module_graph)
