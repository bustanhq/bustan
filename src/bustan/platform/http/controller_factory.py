"""Factory for controller instantiation and pipeline component resolution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeVar

from ...common.decorators.injectable import get_provider_metadata
from ...common.types import ProviderScope
from ...contracts import HttpRequest
from ...core.errors import InvalidControllerError, InvalidPipelineError
from ...core.ioc.container import Container
from ...core.module.dynamic import ModuleKey
from ...core.utils import _qualname
from ...pipeline.filters import ExceptionFilter
from ...pipeline.guards import Guard
from ...pipeline.interceptors import Interceptor
from ...pipeline.metadata import PipelineMetadata
from ...pipeline.pipes import Pipe
from .compiler import GlobalPipelineProvider
from .metadata import get_controller_metadata

if TYPE_CHECKING:
    from ...testing.overrides import PipelineOverrideRegistry

ComponentT = TypeVar("ComponentT")


class ControllerFactory:
    """Manages the creation and DI-resolution of controllers and their pipelines."""

    def __init__(
        self,
        container: Container,
        *,
        pipeline_override_registry: PipelineOverrideRegistry | None = None,
    ) -> None:
        self.container = container
        self.pipeline_override_registry = pipeline_override_registry

    async def instantiate_async(
        self,
        controller_cls: type[object],
        *,
        module: ModuleKey,
        request: HttpRequest,
    ) -> object:
        """Instantiate a controller for a request, awaiting asynchronous dependencies.

        This is the driver the HTTP runtime uses, and the only one a request goes
        through, so a controller may depend on a provider only an awaited factory can
        build whatever lifetime that provider declares.
        """
        scope = self._controller_scope(controller_cls)
        controller_key = (module, controller_cls)

        if scope is ProviderScope.TRANSIENT:
            return await self.container.instantiate_class_async(
                controller_cls, module=module, request=request
            )

        if scope is ProviderScope.REQUEST:
            request_cache = self.container.scope_manager.get_request_controller_cache(request)
            instance = request_cache.get(controller_key)
            if instance is None:
                instance = await self.container.instantiate_class_async(
                    controller_cls, module=module, request=request
                )
                request_cache[controller_key] = instance
            return instance

        instance = self.container.scope_manager.get_controller_singleton(controller_key)
        if instance is not None:
            return instance

        # A threading lock held across an await would stop the event loop, so the
        # awaited driver serializes on the awaited lock table under the same key.
        async with self.container.scope_manager.get_async_construction_lock(controller_key):
            instance = self.container.scope_manager.get_controller_singleton(controller_key)
            if instance is None:
                instance = await self.container.instantiate_class_async(
                    controller_cls, module=module, request=request
                )
                self.container.scope_manager.set_controller_singleton(controller_key, instance)
        assert instance is not None
        return instance

    def _controller_scope(self, controller_cls: type[object]) -> ProviderScope:
        """Return the lifetime a controller declared, refusing one it cannot have."""

        metadata = get_controller_metadata(controller_cls)
        scope = metadata.scope if metadata is not None else ProviderScope.SINGLETON
        if scope in {ProviderScope.TRANSIENT, ProviderScope.REQUEST, ProviderScope.SINGLETON}:
            return scope

        # Every remaining lifetime partitions instances by a key a controller does not
        # carry, so serving one would mean handing one caller's instance to the next.
        # The compiler refuses such a declaration while the application is built; this
        # guard keeps the fall-through from quietly reappearing behind a new scope.
        raise InvalidControllerError(
            f"{_qualname(controller_cls)} declares scope {scope.value!r}, which a "
            "controller cannot have; declare a singleton, request or transient controller"
        )

    async def resolve_pipeline_async(
        self,
        metadata: PipelineMetadata,
        *,
        module: ModuleKey,
        request: HttpRequest,
    ) -> ResolvedPipeline:
        """Resolve a route's pipeline for one request, awaiting asynchronous factories."""
        metadata = self._overridden(metadata)
        return ResolvedPipeline(
            guards=await self.resolve_components_async(
                metadata.guards, Guard, module=module, request=request, kind="guard"
            ),
            pipes=await self.resolve_components_async(
                metadata.pipes, Pipe, module=module, request=request, kind="pipe"
            ),
            interceptors=await self.resolve_components_async(
                metadata.interceptors,
                Interceptor,
                module=module,
                request=request,
                kind="interceptor",
            ),
            filters=await self.resolve_components_async(
                metadata.filters, ExceptionFilter, module=module, request=request, kind="filter"
            ),
        )

    def resolve_components(
        self,
        components: tuple[object, ...],
        expected_type: type[ComponentT],
        *,
        module: ModuleKey,
        request: HttpRequest,
        kind: str,
    ) -> tuple[ComponentT, ...]:
        """Resolve individual components (instances or classes) into instances."""
        resolved: list[ComponentT] = []
        for component in components:
            source = self._container_source(component, module)
            if source is None:
                instances: tuple[object, ...] = (self._build_unmanaged(component, kind),)
            else:
                token, owner = source
                instances = self._expanded(
                    component, self.container.resolve(token, module=owner, request=request)
                )
            resolved.extend(self._verified(instance, expected_type, kind) for instance in instances)
        return tuple(resolved)

    async def resolve_components_async(
        self,
        components: tuple[object, ...],
        expected_type: type[ComponentT],
        *,
        module: ModuleKey,
        request: HttpRequest,
        kind: str,
    ) -> tuple[ComponentT, ...]:
        """Resolve pipeline components for one request, awaiting asynchronous factories."""
        resolved: list[ComponentT] = []
        for component in components:
            source = self._container_source(component, module)
            if source is None:
                instances: tuple[object, ...] = (self._build_unmanaged(component, kind),)
            else:
                token, owner = source
                instances = self._expanded(
                    component,
                    await self.container.resolve_async(token, module=owner, request=request),
                )
            resolved.extend(self._verified(instance, expected_type, kind) for instance in instances)
        return tuple(resolved)

    def _overridden(self, metadata: PipelineMetadata) -> PipelineMetadata:
        if self.pipeline_override_registry is None:
            return metadata
        return self.pipeline_override_registry.apply_to_metadata(metadata)

    def _container_source(
        self, component: object, module: ModuleKey
    ) -> tuple[object, ModuleKey] | None:
        """Return the token and module a component is built from, or ``None``.

        A component the container knows about is built by the container, so it receives
        its dependencies and its declared lifetime. Anything else is a plain class or an
        instance the author wrote out, and is built here.
        """

        if isinstance(component, GlobalPipelineProvider):
            return component.token, component.module
        if not isinstance(component, type):
            return None
        if get_provider_metadata(component) is not None or self._is_registered(component, module):
            return component, module
        return None

    def _expanded(self, component: object, resolved: object) -> tuple[object, ...]:
        """Expand a global token bound to a list into the components it names.

        One global token may stand for several components, so a module registers more
        than one global guard, pipe, interceptor or filter by binding a list under the
        token. They run in the order the list was written.
        """

        if isinstance(component, GlobalPipelineProvider) and isinstance(resolved, (list, tuple)):
            return tuple(resolved)
        return (resolved,)

    def _is_registered(self, component: type[object], module: ModuleKey) -> bool:
        """Return whether a module can see a provider registered under this class."""

        return component in self.container.registry.module_visibility.get(module, {})

    def _build_unmanaged(self, component: object, kind: str) -> object:
        """Build a component the container does not know about, or refuse it."""

        if not isinstance(component, type):
            return component
        try:
            return component()
        except TypeError as exc:
            raise InvalidPipelineError(
                f"{kind.capitalize()} {_qualname(component)} must be an instance, "
                "a no-argument class, or an @Injectable provider"
            ) from exc

    def _verified(self, instance: object, expected_type: type[ComponentT], kind: str) -> ComponentT:
        """Return an instance that implements the contract its slot requires."""

        if not isinstance(instance, expected_type):
            raise InvalidPipelineError(
                f"Resolved {kind} {_qualname(type(instance))} must inherit from "
                f"{expected_type.__name__}"
            )
        return instance


@dataclass(frozen=True, slots=True)
class ResolvedPipeline:
    """Container for instantiated pipeline components."""

    guards: tuple[Guard, ...]
    pipes: tuple[Pipe, ...]
    interceptors: tuple[Interceptor, ...]
    filters: tuple[ExceptionFilter, ...]
