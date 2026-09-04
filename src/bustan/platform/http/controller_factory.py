"""Factory for controller instantiation and pipeline component resolution."""

from __future__ import annotations
from dataclasses import dataclass

from typing import TYPE_CHECKING, TypeVar, cast

from ...core.ioc.container import Container
from ...core.errors import InvalidControllerError, InvalidPipelineError
from ...core.module.dynamic import ModuleKey
from ...common.types import ProviderScope
from ...core.utils import _qualname
from ...common.constants import BUSTAN_PROVIDER_ATTR
from ...pipeline.metadata import PipelineMetadata
from ...pipeline.guards import Guard
from ...pipeline.pipes import Pipe
from ...pipeline.interceptors import Interceptor
from ...pipeline.filters import ExceptionFilter
from starlette.requests import Request
from .metadata import get_controller_metadata

if TYPE_CHECKING:
    from ...testing.overrides import PipelineOverrideRegistry

ComponentT = TypeVar("ComponentT")


def controller_scope(controller_cls: type[object]) -> ProviderScope:
    """Return a controller's declared scope, refusing the durable one.

    Durable scope partitions instances by a key a provider derives from the
    request. A controller has no such key of its own, so a durable controller
    would be built once and then shared by every partition it was declared to
    keep apart. Declare the controller request-scoped or transient and inject a
    durable provider instead.
    """

    metadata = get_controller_metadata(controller_cls)
    scope = metadata.scope if metadata is not None else ProviderScope.SINGLETON
    if scope is ProviderScope.DURABLE:
        raise InvalidControllerError(
            f"{_qualname(controller_cls)} declares durable scope, which controllers do not "
            "support. Declare the controller request-scoped or transient and inject a "
            "durable-scoped provider for the partitioned state"
        )
    return scope


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
        self.container.resolver.validate_graph_scopes(self._declared_controller_scopes())

    def _declared_controller_scopes(self) -> dict[type[object], ProviderScope]:
        """Return the scope every registered controller is built under."""

        return {
            controller_cls: controller_scope(controller_cls)
            for controller_cls in self.container.registry.controller_modules
        }

    def instantiate(
        self,
        controller_cls: type[object],
        *,
        module: ModuleKey,
        request: Request,
    ) -> object:
        """Instantiate a controller according to its declared scope."""
        scope = controller_scope(controller_cls)
        controller_key = (module, controller_cls)

        if scope is ProviderScope.TRANSIENT:
            return self._build(controller_cls, module, request, scope)

        if scope is ProviderScope.REQUEST:
            request_cache = self.container.scope_manager.get_request_controller_cache(request)
            instance = request_cache.get(controller_key)
            if instance is None:
                instance = self._build(controller_cls, module, request, scope)
                request_cache[controller_key] = instance
            return instance

        instance = self.container.scope_manager.get_controller_singleton(controller_key)
        if instance is not None:
            return instance

        lock = self.container.scope_manager.get_controller_singleton_lock(controller_key)
        with lock:
            instance = self.container.scope_manager.get_controller_singleton(controller_key)
            if instance is None:
                instance = self._build(controller_cls, module, request, scope)
                self.container.scope_manager.set_controller_singleton(controller_key, instance)
        assert instance is not None
        return instance

    def _build(
        self,
        controller_cls: type[object],
        module: ModuleKey,
        request: Request,
        scope: ProviderScope,
    ) -> object:
        """Construct a controller, telling the resolver how long it will be kept."""

        return self.container.resolver.instantiate_class(
            controller_cls, module=module, request=request, owner_scope=scope
        )

    def resolve_pipeline(
        self,
        metadata: PipelineMetadata,
        *,
        module: ModuleKey,
        request: Request,
    ) -> ResolvedPipeline:
        """Resolve all classes in a pipeline metadata into injectable instances."""
        if self.pipeline_override_registry is not None:
            metadata = self.pipeline_override_registry.apply_to_metadata(metadata)
        return ResolvedPipeline(
            guards=self.resolve_components(
                metadata.guards, Guard, module=module, request=request, kind="guard"
            ),
            pipes=self.resolve_components(
                metadata.pipes, Pipe, module=module, request=request, kind="pipe"
            ),
            interceptors=self.resolve_components(
                metadata.interceptors,
                Interceptor,
                module=module,
                request=request,
                kind="interceptor",
            ),
            filters=self.resolve_components(
                metadata.filters, ExceptionFilter, module=module, request=request, kind="filter"
            ),
        )

    def resolve_components(
        self,
        components: tuple[object, ...],
        expected_type: type[ComponentT],
        *,
        module: ModuleKey,
        request: Request,
        kind: str,
    ) -> tuple[ComponentT, ...]:
        """Resolve individual components (instances or classes) into instances."""
        resolved: list[ComponentT] = []

        for component in components:
            instance = component
            if isinstance(component, type):
                comp_type = cast(type[ComponentT], component)
                if getattr(comp_type, BUSTAN_PROVIDER_ATTR, None) is not None:
                    instance = self.container.resolve(comp_type, module=module, request=request)
                else:
                    try:
                        instance = comp_type()
                    except TypeError as exc:
                        raise InvalidPipelineError(
                            f"{kind.capitalize()} {_qualname(comp_type)} must be an instance, "
                            "a no-argument class, or an @Injectable provider"
                        ) from exc

            if not isinstance(instance, expected_type):
                raise InvalidPipelineError(
                    f"Resolved {kind} {_qualname(type(instance))} must inherit from "
                    f"{expected_type.__name__}"
                )
            resolved.append(instance)

        return tuple(resolved)


@dataclass(frozen=True, slots=True)
class ResolvedPipeline:
    """Container for instantiated pipeline components."""

    guards: tuple[Guard, ...]
    pipes: tuple[Pipe, ...]
    interceptors: tuple[Interceptor, ...]
    filters: tuple[ExceptionFilter, ...]
