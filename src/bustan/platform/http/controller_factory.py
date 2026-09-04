"""Factory for controller instantiation and pipeline component resolution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeVar, cast

from starlette.requests import Request

from ...common.decorators.injectable import get_provider_metadata
from ...common.types import ProviderScope
from ...core.errors import InvalidControllerError, InvalidPipelineError
from ...core.ioc.container import Container
from ...core.module.dynamic import ModuleKey
from ...core.utils import _qualname
from ...pipeline.filters import ExceptionFilter
from ...pipeline.guards import Guard
from ...pipeline.interceptors import Interceptor
from ...pipeline.metadata import PipelineMetadata
from ...pipeline.pipes import Pipe
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

    def instantiate(
        self,
        controller_cls: type[object],
        *,
        module: ModuleKey,
        request: Request,
    ) -> object:
        """Instantiate a controller according to its declared scope."""
        metadata = get_controller_metadata(controller_cls)
        scope = metadata.scope if metadata is not None else ProviderScope.SINGLETON
        controller_key = (module, controller_cls)

        if scope is ProviderScope.TRANSIENT:
            return self.container.instantiate_class(controller_cls, module=module, request=request)

        if scope is ProviderScope.REQUEST:
            request_cache = self.container.scope_manager.get_request_controller_cache(request)
            instance = request_cache.get(controller_key)
            if instance is None:
                instance = self.container.instantiate_class(
                    controller_cls, module=module, request=request
                )
                request_cache[controller_key] = instance
            return instance

        if scope is not ProviderScope.SINGLETON:
            # Every remaining lifetime partitions instances by a key a controller does not
            # carry, so serving one would mean handing one caller's instance to the next.
            # The compiler refuses such a declaration while the application is built; this
            # guard keeps the fall-through from quietly reappearing behind a new scope.
            raise InvalidControllerError(
                f"{_qualname(controller_cls)} declares scope {scope.value!r}, which a "
                "controller cannot have; declare a singleton, request or transient controller"
            )

        instance = self.container.scope_manager.get_controller_singleton(controller_key)
        if instance is not None:
            return instance

        lock = self.container.scope_manager.get_controller_singleton_lock(controller_key)
        with lock:
            instance = self.container.scope_manager.get_controller_singleton(controller_key)
            if instance is None:
                instance = self.container.instantiate_class(
                    controller_cls, module=module, request=request
                )
                self.container.scope_manager.set_controller_singleton(controller_key, instance)
        assert instance is not None
        return instance

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
                if get_provider_metadata(comp_type) is not None:
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
