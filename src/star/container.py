"""Dependency injection container assembly and runtime resolution."""

from __future__ import annotations

import inspect
import sys
from contextvars import ContextVar, Token
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TypeVar, cast, get_type_hints

from dependency_injector import providers
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response

from .errors import InvalidControllerError, ProviderResolutionError
from .metadata import ProviderScope, get_provider_metadata
from .module_graph import ModuleGraph

ProviderFactory = Callable[[], object]
ResolvedT = TypeVar("ResolvedT")
NO_OVERRIDE = object()
REQUEST_SCOPE_CACHE_ATTR = "star_request_provider_cache"

FRAMEWORK_OWNED_TYPES = frozenset({Request, Response, Starlette})


@dataclass(frozen=True, slots=True)
class ResolutionContext:
    """Resolution-time state passed through constructor injection."""

    module: type[object]
    dependency_stack: tuple[type[object], ...] = ()
    request: Request | None = None


@dataclass(frozen=True, slots=True)
class ProviderRegistration:
    """Container-side registration record for a provider class."""

    provider: type[object]
    module: type[object]
    scope: ProviderScope
    factory: ProviderFactory | None = field(repr=False)


@dataclass(frozen=True, slots=True)
class ModuleRegistry:
    """Visibility map for providers reachable from one module."""

    module: type[object]
    controllers: tuple[type[object], ...]
    accessible_provider_modules: Mapping[type[object], type[object]] = field(repr=False)

    def declaring_module_for(self, provider_cls: type[object]) -> type[object] | None:
        """Return the module that legally exposes a provider to this module."""

        return self.accessible_provider_modules.get(provider_cls)


class ContainerAdapter:
    """Resolve providers and controllers against a validated module graph."""

    def __init__(self, module_graph: ModuleGraph) -> None:
        self.module_graph = module_graph
        self._module_registries = MappingProxyType(self._build_module_registries())
        self._provider_registrations: dict[tuple[type[object], type[object]], ProviderRegistration] = {}
        self._provider_overrides: dict[tuple[type[object], type[object]], object] = {}
        self._controller_modules: dict[type[object], type[object]] = {}
        self._controller_factories: dict[type[object], ProviderFactory] = {}
        self._active_request: ContextVar[Request | None] = ContextVar(
            "star_active_request",
            default=None,
        )
        self._resolution_stack: ContextVar[tuple[type[object], ...]] = ContextVar(
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
        provider_cls: type[ResolvedT],
        module_cls: type[object],
        *,
        request: Request | None = None,
    ) -> ResolvedT:
        """Resolve a provider visible from the given module.

        When a request is supplied, request-scoped providers are cached on that
        request so the same object instance is reused throughout the pipeline.
        """

        active_request_token = self._push_active_request(request)
        try:
            module_registry = self.get_module_registry(module_cls)
            declaring_module = module_registry.declaring_module_for(provider_cls)
            if declaring_module is None:
                raise ProviderResolutionError(
                    f"{_qualname(provider_cls)} is not available to {_qualname(module_cls)}. "
                    "Dependencies must come from the same module or an imported module export"
                )

            provider_override = self._provider_overrides.get((declaring_module, provider_cls), NO_OVERRIDE)
            if provider_override is not NO_OVERRIDE:
                return cast(ResolvedT, provider_override)

            return self._resolve_registered_provider(provider_cls, declaring_module)
        finally:
            self._reset_active_request(active_request_token)

    def has_provider_override(
        self,
        provider_cls: type[object],
        *,
        module_cls: type[object] | None = None,
    ) -> bool:
        """Return whether an override exists for the selected provider."""

        override_key = self._resolve_override_key(provider_cls, module_cls)
        return override_key in self._provider_overrides

    def get_provider_override(
        self,
        provider_cls: type[ResolvedT],
        *,
        module_cls: type[object] | None = None,
    ) -> ResolvedT:
        """Return the active override for a provider."""

        override_key = self._resolve_override_key(provider_cls, module_cls)
        try:
            return cast(ResolvedT, self._provider_overrides[override_key])
        except KeyError as exc:
            raise ProviderResolutionError(
                f"No provider override is registered for {_qualname(provider_cls)}"
            ) from exc

    def set_provider_override(
        self,
        provider_cls: type[ResolvedT],
        replacement: ResolvedT,
        *,
        module_cls: type[object] | None = None,
    ) -> None:
        """Register a replacement object for a provider."""

        override_key = self._resolve_override_key(provider_cls, module_cls)
        self._provider_overrides[override_key] = replacement

    def clear_provider_override(
        self,
        provider_cls: type[object],
        *,
        module_cls: type[object] | None = None,
    ) -> None:
        """Remove any override registered for a provider."""

        override_key = self._resolve_override_key(provider_cls, module_cls)
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
            accessible_provider_modules: dict[type[object], type[object]] = {
                provider_cls: node.module for provider_cls in node.providers
            }

            for imported_module in node.imports:
                for exported_provider in self.module_graph.exports_for(imported_module):
                    existing_module = accessible_provider_modules.get(exported_provider)
                    if existing_module is not None and existing_module is not node.module:
                        raise ProviderResolutionError(
                            f"{_qualname(node.module)} can access {_qualname(exported_provider)} "
                            f"from both {_qualname(existing_module)} and {_qualname(imported_module)}"
                        )

                    accessible_provider_modules.setdefault(exported_provider, imported_module)

            module_registries[node.module] = ModuleRegistry(
                module=node.module,
                controllers=node.controllers,
                accessible_provider_modules=MappingProxyType(accessible_provider_modules),
            )

        return module_registries

    def _build_registrations(self) -> None:
        for node in self.module_graph.nodes:
            for provider_cls in node.providers:
                provider_metadata = get_provider_metadata(provider_cls)
                assert provider_metadata is not None

                provider_factory = self._build_provider_factory(
                    provider_cls,
                    node.module,
                    provider_metadata.scope,
                )
                self._provider_registrations[(node.module, provider_cls)] = ProviderRegistration(
                    provider=provider_cls,
                    module=node.module,
                    scope=provider_metadata.scope,
                    factory=provider_factory,
                )

            for controller_cls in node.controllers:
                existing_module = self._controller_modules.get(controller_cls)
                if existing_module is not None and existing_module is not node.module:
                    raise InvalidControllerError(
                        f"{_qualname(controller_cls)} is declared in multiple modules: "
                        f"{_qualname(existing_module)} and {_qualname(node.module)}"
                    )

                self._controller_modules[controller_cls] = node.module
                self._controller_factories[controller_cls] = cast(
                    ProviderFactory,
                    providers.Factory(self._instantiate_class, controller_cls, node.module),
                )

    def _build_provider_factory(
        self,
        provider_cls: type[object],
        module_cls: type[object],
        scope: ProviderScope,
    ) -> ProviderFactory | None:
        if scope is ProviderScope.REQUEST:
            return None

        if scope is ProviderScope.TRANSIENT:
            return cast(
                ProviderFactory,
                providers.Factory(self._instantiate_class, provider_cls, module_cls),
            )

        return cast(
            ProviderFactory,
            providers.Singleton(self._instantiate_class, provider_cls, module_cls),
        )

    def _resolve_registered_provider(
        self,
        provider_cls: type[ResolvedT],
        module_cls: type[object],
    ) -> ResolvedT:
        registration_key = (module_cls, provider_cls)
        try:
            registration = self._provider_registrations[registration_key]
        except KeyError as exc:
            raise ProviderResolutionError(
                f"{_qualname(provider_cls)} is not registered in {_qualname(module_cls)}"
            ) from exc

        active_request = self._active_request.get()
        request_scope_cache: dict[tuple[type[object], type[object]], object] | None = None
        if registration.scope is ProviderScope.REQUEST:
            if active_request is None:
                raise ProviderResolutionError(
                    f"Request-scoped provider {_qualname(provider_cls)} requires an active request"
                )

            # Request-scoped objects are stored on request.state so every
            # resolution in the same request observes the same instance.
            request_scope_cache = self._get_request_scope_cache(active_request)
            cached_instance = request_scope_cache.get(registration_key, NO_OVERRIDE)
            if cached_instance is not NO_OVERRIDE:
                return cast(ResolvedT, cached_instance)

        current_stack = self._resolution_stack.get()
        # Track the active resolution chain so circular dependencies surface as
        # a deterministic error instead of recursive instantiation.
        if provider_cls in current_stack:
            cycle_path = " -> ".join(
                _display_name(dependency) for dependency in (*current_stack, provider_cls)
            )
            raise ProviderResolutionError(f"Circular provider dependencies detected: {cycle_path}")

        stack_token = self._resolution_stack.set((*current_stack, provider_cls))
        try:
            if registration.scope is ProviderScope.REQUEST:
                instance = self._instantiate_class(provider_cls, module_cls)
                assert request_scope_cache is not None
                request_scope_cache[registration_key] = instance
                return instance

            provider_factory = registration.factory
            assert provider_factory is not None
            return cast(ResolvedT, provider_factory())
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

        for provider_cls in module_registry.accessible_provider_modules:
            namespace.setdefault(provider_cls.__name__, provider_cls)

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
    ) -> dict[tuple[type[object], type[object]], object]:
        request_scope_cache = getattr(request.state, REQUEST_SCOPE_CACHE_ATTR, None)
        if request_scope_cache is None:
            request_scope_cache = {}
            setattr(request.state, REQUEST_SCOPE_CACHE_ATTR, request_scope_cache)
        return cast(dict[tuple[type[object], type[object]], object], request_scope_cache)

    def _resolve_override_key(
        self,
        provider_cls: type[object],
        module_cls: type[object] | None,
    ) -> tuple[type[object], type[object]]:
        if module_cls is not None:
            override_key = (module_cls, provider_cls)
            if override_key not in self._provider_registrations:
                raise ProviderResolutionError(
                    f"{_qualname(provider_cls)} is not registered in {_qualname(module_cls)}"
                )
            return override_key

        declaring_modules = [
            registered_module
            for registered_module, registered_provider in self._provider_registrations
            if registered_provider is provider_cls
        ]

        if not declaring_modules:
            raise ProviderResolutionError(f"{_qualname(provider_cls)} is not registered in the container")

        if len(declaring_modules) > 1:
            module_names = ", ".join(_qualname(registered_module) for registered_module in declaring_modules)
            raise ProviderResolutionError(
                f"{_qualname(provider_cls)} is registered in multiple modules ({module_names}); "
                "specify module_cls when overriding it"
            )

        return declaring_modules[0], provider_cls


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