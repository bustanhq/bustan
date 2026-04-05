"""Dependency injection container assembly and runtime resolution."""

from __future__ import annotations

import inspect
import sys
import threading
from contextvars import ContextVar, Token
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TypeVar, cast, get_type_hints

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response

from .errors import InvalidControllerError, ProviderResolutionError
from .metadata import (
    ClassProviderDef,
    ExistingProviderDef,
    FactoryProviderDef,
    ProviderDef,
    ProviderScope,
    ValueProviderDef,
    get_provider_metadata,
)
from .module_graph import ModuleGraph

ProviderFactory = Callable[[], object]
ResolvedT = TypeVar("ResolvedT")
NO_OVERRIDE = object()
REQUEST_SCOPE_CACHE_ATTR = "star_request_provider_cache"

FRAMEWORK_OWNED_TYPES = frozenset({Request, Response, Starlette})

_UNSET = object()


class _FactoryProvider:
    """Creates a new instance on every call."""

    __slots__ = ("_fn", "_args")

    def __init__(self, fn: Callable[..., object], *args: object) -> None:
        self._fn = fn
        self._args = args

    def __call__(self) -> object:
        return self._fn(*self._args)


class _SingletonProvider:
    """Creates one instance on first call and returns the same object thereafter."""

    __slots__ = ("_fn", "_args", "_instance", "_lock")

    def __init__(self, fn: Callable[..., object], *args: object) -> None:
        self._fn = fn
        self._args = args
        self._instance: object = _UNSET
        self._lock = threading.Lock()

    def __call__(self) -> object:
        if self._instance is _UNSET:
            with self._lock:
                if self._instance is _UNSET:
                    self._instance = self._fn(*self._args)
        return self._instance


@dataclass(frozen=True, slots=True)
class ResolutionContext:
    """Resolution-time state passed through constructor injection."""

    module: type[object]
    dependency_stack: tuple[object, ...] = ()
    request: Request | None = None


@dataclass(frozen=True, slots=True)
class ProviderRegistration:
    """Container-side registration record for a provider."""

    token: object
    module: type[object]
    scope: ProviderScope
    factory: ProviderFactory = field(repr=False)


@dataclass(frozen=True, slots=True)
class ModuleRegistry:
    """Visibility map for providers reachable from one module."""

    module: type[object]
    controllers: tuple[type[object], ...]
    accessible_provider_modules: Mapping[object, type[object]] = field(repr=False)

    def declaring_module_for(self, token: object) -> type[object] | None:
        """Return the module that legally exposes a provider to this module."""

        return self.accessible_provider_modules.get(token)


class ContainerAdapter:
    """Resolve providers and controllers against a validated module graph."""

    def __init__(self, module_graph: ModuleGraph) -> None:
        self.module_graph = module_graph
        self._module_registries = MappingProxyType(self._build_module_registries())
        self._provider_registrations: dict[tuple[type[object], object], ProviderRegistration] = {}
        self._provider_overrides: dict[tuple[type[object], object], object] = {}
        self._controller_modules: dict[type[object], type[object]] = {}
        self._controller_factories: dict[type[object], ProviderFactory] = {}
        self._active_request: ContextVar[Request | None] = ContextVar(
            "star_active_request",
            default=None,
        )
        self._resolution_stack: ContextVar[tuple[object, ...]] = ContextVar(
            "star_resolution_stack",
            default=(),
        )
        self._build_registrations()

    def get_module_registry(self, module_cls: type[object]) -> ModuleRegistry:
        """Return the visibility registry for a known module."""

        try:
            return self._module_registries[module_cls]
        except KeyError as exc:
            raise ProviderResolutionError(
                f"{_qualname(module_cls)} is not part of the application container"
            ) from exc

    def resolve_provider(
        self,
        token: object,
        module_cls: type[object],
        *,
        request: Request | None = None,
    ) -> object:
        """Resolve a provider visible from the given module.

        When a request is supplied, request-scoped providers are cached on that
        request so the same object instance is reused throughout the pipeline.
        """

        active_request_token = self._push_active_request(request)
        try:
            module_registry = self.get_module_registry(module_cls)
            declaring_module = module_registry.declaring_module_for(token)
            if declaring_module is None:
                raise ProviderResolutionError(
                    f"{_qualname(token)} is not available to {_qualname(module_cls)}. "
                    "Dependencies must come from the same module or an imported module export"
                )

            provider_override = self._provider_overrides.get((declaring_module, token), NO_OVERRIDE)
            if provider_override is not NO_OVERRIDE:
                return provider_override

            return self._resolve_registered_provider(token, declaring_module)
        finally:
            self._reset_active_request(active_request_token)

    def has_provider_override(
        self,
        token: object,
        *,
        module_cls: type[object] | None = None,
    ) -> bool:
        """Return whether an override exists for the selected provider."""

        override_key = self._resolve_override_key(token, module_cls)
        return override_key in self._provider_overrides

    def get_provider_override(
        self,
        token: object,
        *,
        module_cls: type[object] | None = None,
    ) -> object:
        """Return the active override for a provider."""

        override_key = self._resolve_override_key(token, module_cls)
        try:
            return self._provider_overrides[override_key]
        except KeyError as exc:
            raise ProviderResolutionError(
                f"No provider override is registered for {_qualname(token)}"
            ) from exc

    def set_provider_override(
        self,
        token: object,
        replacement: object,
        *,
        module_cls: type[object] | None = None,
    ) -> None:
        """Register a replacement object for a provider."""

        override_key = self._resolve_override_key(token, module_cls)
        self._provider_overrides[override_key] = replacement

    def clear_provider_override(
        self,
        token: object,
        *,
        module_cls: type[object] | None = None,
    ) -> None:
        """Remove any override registered for a provider."""

        override_key = self._resolve_override_key(token, module_cls)
        self._provider_overrides.pop(override_key, None)

    def resolve_controller(
        self,
        controller_cls: type[ResolvedT],
        *,
        request: Request | None = None,
    ) -> ResolvedT:
        """Resolve a fresh controller instance for request handling."""

        module_cls = self._controller_modules.get(controller_cls)
        if module_cls is None:
            raise InvalidControllerError(
                f"{_qualname(controller_cls)} is not registered in the application container"
            )

        active_request_token = self._push_active_request(request)
        try:
            controller_factory = self._controller_factories[controller_cls]
            return cast(ResolvedT, controller_factory())
        finally:
            self._reset_active_request(active_request_token)

    def _build_module_registries(self) -> dict[type[object], ModuleRegistry]:
        module_registries: dict[type[object], ModuleRegistry] = {}

        for node in self.module_graph.nodes:
            # Providers are visible from their own module plus explicit exports
            # from directly imported modules. Everything else stays private.
            accessible_provider_modules: dict[object, type[object]] = {
                token: node.module for token in node.providers
            }

            for imported_module in node.imports:
                for exported_token in self.module_graph.exports_for(imported_module):
                    existing_module = accessible_provider_modules.get(exported_token)
                    if existing_module is not None and existing_module is not node.module:
                        raise ProviderResolutionError(
                            f"{_qualname(node.module)} can access {_qualname(exported_token)} "
                            f"from both {_qualname(existing_module)} and {_qualname(imported_module)}"
                        )

                    accessible_provider_modules.setdefault(exported_token, imported_module)

            module_registries[node.module] = ModuleRegistry(
                module=node.module,
                controllers=node.controllers,
                accessible_provider_modules=MappingProxyType(accessible_provider_modules),
            )

        return module_registries

    def _build_registrations(self) -> None:
        for node in self.module_graph.nodes:
            for pdef in node.provider_defs:
                token = pdef.provide
                factory, scope = self._build_provider_factory(pdef, node.module)
                self._provider_registrations[(node.module, token)] = ProviderRegistration(
                    token=token,
                    module=node.module,
                    scope=scope,
                    factory=factory,
                )

            for controller_cls in node.controllers:
                existing_module = self._controller_modules.get(controller_cls)
                if existing_module is not None and existing_module is not node.module:
                    raise InvalidControllerError(
                        f"{_qualname(controller_cls)} is declared in multiple modules: "
                        f"{_qualname(existing_module)} and {_qualname(node.module)}"
                    )

                self._controller_modules[controller_cls] = node.module
                self._controller_factories[controller_cls] = _FactoryProvider(
                    self._instantiate_class, controller_cls, node.module
                )

    def _build_provider_factory(
        self,
        provider_def: ProviderDef,
        module_cls: type[object],
    ) -> tuple[ProviderFactory, ProviderScope]:
        """Return a (factory, scope) pair for the given ProviderDef."""

        if isinstance(provider_def, ValueProviderDef):
            value = provider_def.use_value
            return _SingletonProvider(lambda: value), ProviderScope.SINGLETON

        if isinstance(provider_def, ExistingProviderDef):
            use_existing = provider_def.use_existing
            # Delegate resolution to the aliased token on every call; the
            # underlying provider handles its own caching.
            return _FactoryProvider(self.resolve_provider, use_existing, module_cls), ProviderScope.TRANSIENT

        if isinstance(provider_def, FactoryProviderDef):
            scope = provider_def.scope
            invoke = self._make_factory_invoke(provider_def.use_factory, provider_def.inject, module_cls)
            if scope is ProviderScope.SINGLETON:
                return _SingletonProvider(invoke), scope
            return _FactoryProvider(invoke), scope

        # ClassProviderDef
        use_class = provider_def.use_class
        scope = provider_def.scope
        if scope is ProviderScope.SINGLETON:
            return _SingletonProvider(self._instantiate_class, use_class, module_cls), scope
        return _FactoryProvider(self._instantiate_class, use_class, module_cls), scope

    def _resolve_registered_provider(
        self,
        token: object,
        module_cls: type[object],
    ) -> object:
        registration_key = (module_cls, token)
        try:
            registration = self._provider_registrations[registration_key]
        except KeyError as exc:
            raise ProviderResolutionError(
                f"{_qualname(token)} is not registered in {_qualname(module_cls)}"
            ) from exc

        active_request = self._active_request.get()
        request_scope_cache: dict[tuple[type[object], object], object] | None = None
        if registration.scope is ProviderScope.REQUEST:
            if active_request is None:
                raise ProviderResolutionError(
                    f"Request-scoped provider {_qualname(token)} requires an active request"
                )

            # Request-scoped objects are stored on request.state so every
            # resolution in the same request observes the same instance.
            request_scope_cache = self._get_request_scope_cache(active_request)
            cached_instance = request_scope_cache.get(registration_key, NO_OVERRIDE)
            if cached_instance is not NO_OVERRIDE:
                return cached_instance

        current_stack = self._resolution_stack.get()
        # Track the active resolution chain so circular dependencies surface as
        # a deterministic error instead of recursive instantiation.
        if token in current_stack:
            cycle_path = " -> ".join(
                _display_name(dependency) for dependency in (*current_stack, token)
            )
            raise ProviderResolutionError(f"Circular provider dependencies detected: {cycle_path}")

        stack_token = self._resolution_stack.set((*current_stack, token))
        try:
            instance = registration.factory()
            if registration.scope is ProviderScope.REQUEST:
                assert request_scope_cache is not None
                request_scope_cache[registration_key] = instance
            return instance
        finally:
            self._resolution_stack.reset(stack_token)

    def _instantiate_class(
        self, class_cls: type[ResolvedT], module_cls: type[object]
    ) -> ResolvedT:
        positional_arguments, keyword_arguments = self._resolve_constructor_dependencies(
            class_cls,
            ResolutionContext(
                module=module_cls,
                dependency_stack=self._resolution_stack.get(),
                request=self._active_request.get(),
            ),
        )
        return class_cls(*positional_arguments, **keyword_arguments)

    def _make_factory_invoke(
        self,
        use_factory: object,
        inject_tokens: tuple[object, ...],
        module_cls: type[object],
    ) -> ProviderFactory:
        """Return a no-arg callable that resolves inject tokens and calls use_factory."""

        def invoke() -> object:
            args = [self.resolve_provider(t, module_cls) for t in inject_tokens]
            return use_factory(*args)  # type: ignore[operator]

        return invoke

    def _resolve_constructor_dependencies(
        self,
        class_cls: type[object],
        context: ResolutionContext,
    ) -> tuple[tuple[object, ...], dict[str, object]]:
        provider_metadata = get_provider_metadata(class_cls)
        owner_is_request_scoped_provider = (
            provider_metadata is not None and provider_metadata.scope is ProviderScope.REQUEST
        )
        owner_is_controller = class_cls in self._controller_modules

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
            # Build a local namespace containing controllers and providers that
            # are visible from this module so forward references can resolve.
            type_hints = get_type_hints(
                constructor,
                globalns=getattr(
                    sys.modules.get(class_cls.__module__),
                    "__dict__",
                    constructor.__globals__,
                ),
                localns=self._build_type_hint_namespace(class_cls, context.module),
            )
        except (NameError, TypeError) as exc:
            raise ProviderResolutionError(
                f"Could not resolve type hints for {_qualname(class_cls)}.__init__: {exc}"
            ) from exc

        positional_arguments: list[object] = []
        keyword_arguments: dict[str, object] = {}

        for parameter in signature.parameters.values():
            if parameter.name == "self":
                continue

            if parameter.kind in (
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            ):
                raise ProviderResolutionError(
                    f"{_qualname(class_cls)}.__init__ uses unsupported variadic parameter "
                    f"{parameter.name!r}"
                )

            annotation = type_hints.get(parameter.name)
            if annotation is None:
                raise ProviderResolutionError(
                    f"{_qualname(class_cls)}.__init__ parameter {parameter.name!r} is missing a type annotation"
                )

            if not isinstance(annotation, type):
                raise ProviderResolutionError(
                    f"{_qualname(class_cls)}.__init__ parameter {parameter.name!r} must use a concrete class annotation"
                )

            if annotation in FRAMEWORK_OWNED_TYPES:
                if (
                    annotation is Request
                    and owner_is_request_scoped_provider
                    and context.request is not None
                ):
                    dependency = context.request
                    if parameter.kind in (
                        inspect.Parameter.POSITIONAL_ONLY,
                        inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    ):
                        positional_arguments.append(dependency)
                    else:
                        keyword_arguments[parameter.name] = dependency
                    continue

                raise ProviderResolutionError(
                    f"{_qualname(class_cls)}.__init__ parameter {parameter.name!r} requests "
                    f"framework-owned type {annotation.__name__}, which is not available in provider DI"
                )

            dependency_declaring_module = self.get_module_registry(context.module).declaring_module_for(
                annotation
            )
            if dependency_declaring_module is not None:
                dependency_registration = self._provider_registrations[
                    (dependency_declaring_module, annotation)
                ]
                # Request-scoped objects can safely flow into controllers and
                # other request-scoped providers, but not into longer-lived
                # singleton or transient providers.
                if (
                    dependency_registration.scope is ProviderScope.REQUEST
                    and not owner_is_request_scoped_provider
                    and not owner_is_controller
                ):
                    raise ProviderResolutionError(
                        f"{_qualname(class_cls)}.__init__ parameter {parameter.name!r} depends on "
                        f"request-scoped provider {_qualname(annotation)}, which can only be injected "
                        "into request-scoped providers or controllers"
                    )

            dependency = self.resolve_provider(annotation, context.module, request=context.request)
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
        module_registry = self.get_module_registry(module_cls)
        namespace: dict[str, object] = {
            class_cls.__name__: class_cls,
            Request.__name__: Request,
            Response.__name__: Response,
            Starlette.__name__: Starlette,
        }

        for controller_cls in module_registry.controllers:
            namespace.setdefault(controller_cls.__name__, controller_cls)

        for token in module_registry.accessible_provider_modules:
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
            if override_key not in self._provider_registrations:
                raise ProviderResolutionError(
                    f"{_qualname(token)} is not registered in {_qualname(module_cls)}"
                )
            return override_key

        declaring_modules = [
            registered_module
            for registered_module, registered_token in self._provider_registrations
            if registered_token is token
        ]

        if not declaring_modules:
            raise ProviderResolutionError(f"{_qualname(token)} is not registered in the container")

        if len(declaring_modules) > 1:
            module_names = ", ".join(_qualname(registered_module) for registered_module in declaring_modules)
            raise ProviderResolutionError(
                f"{_qualname(token)} is registered in multiple modules ({module_names}); "
                "specify module_cls when overriding it"
            )

        return declaring_modules[0], token


def build_container(module_graph: ModuleGraph) -> ContainerAdapter:
    """Build the runtime container for a validated module graph."""

    return ContainerAdapter(module_graph)


def _display_name(target: object) -> str:
    if isinstance(target, type):
        return target.__name__
    return repr(target)


def _qualname(target: object) -> str:
    if isinstance(target, type):
        return f"{target.__module__}.{target.__qualname__}"
    return repr(target)