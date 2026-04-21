"""Factory for controller instantiation and pipeline component resolution."""

from __future__ import annotations
from dataclasses import dataclass

from typing import TypeVar, cast

from ...core.ioc.container import Container
from ...core.errors import InvalidPipelineError
from ...core.module.dynamic import ModuleKey
from ...core.utils import _qualname
from ...common.constants import BUSTAN_PROVIDER_ATTR
from ...pipeline.metadata import PipelineMetadata
from ...pipeline.guards import Guard
from ...pipeline.pipes import Pipe
from ...pipeline.interceptors import Interceptor
from ...pipeline.filters import ExceptionFilter
from starlette.requests import Request

ComponentT = TypeVar("ComponentT")


class ControllerFactory:
    """Manages the creation and DI-resolution of controllers and their pipelines."""

    def __init__(self, container: Container) -> None:
        self.container = container

    def instantiate(
        self,
        controller_cls: type[object],
        *,
        module: ModuleKey,
        request: Request,
    ) -> object:
        """Create a fresh instance of a controller using the container."""
        return self.container.instantiate_class(controller_cls, module=module, request=request)

    def resolve_pipeline(
        self,
        metadata: PipelineMetadata,
        *,
        module: ModuleKey,
        request: Request,
    ) -> ResolvedPipeline:
        """Resolve all classes in a pipeline metadata into injectable instances."""
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
