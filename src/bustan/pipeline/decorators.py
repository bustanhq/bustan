"""Decorators for pipeline components."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar, cast

from ..core.errors import InvalidPipelineError
from ..core.utils import _unwrap_handler
from .metadata import (
    extend_controller_pipeline_metadata,
    extend_handler_pipeline_metadata,
)

DecoratedT = TypeVar("DecoratedT", bound=object)


def UseGuards(*guards: object) -> Callable[[DecoratedT], DecoratedT]:
    """Attach one or more guards to a controller or handler."""
    return _pipeline_decorator("guards", guards)


def UsePipes(*pipes: object) -> Callable[[DecoratedT], DecoratedT]:
    """Attach one or more pipes to a controller or handler."""
    return _pipeline_decorator("pipes", pipes)


def UseInterceptors(*interceptors: object) -> Callable[[DecoratedT], DecoratedT]:
    """Attach one or more interceptors to a controller or handler."""
    return _pipeline_decorator("interceptors", interceptors)


def UseFilters(*filters: object) -> Callable[[DecoratedT], DecoratedT]:
    """Attach one or more exception filters to a controller or handler."""
    return _pipeline_decorator("filters", filters)


def _pipeline_decorator(
    field_name: str,
    components: tuple[object, ...],
) -> Callable[[DecoratedT], DecoratedT]:
    """Create a decorator that attaches components to a controller or handler pipeline."""
    if not components:
        raise InvalidPipelineError(f"@Use{field_name.capitalize()} requires at least one component")

    def decorate(target: DecoratedT) -> DecoratedT:
        if isinstance(target, type):
            return cast(
                DecoratedT,
                extend_controller_pipeline_metadata(target, **{field_name: components}),
            )

        handler_function = _unwrap_handler(target)
        if handler_function is None:
            raise InvalidPipelineError(
                f"@Use{field_name.capitalize()} can only decorate controller classes or handler callables"
            )

        extend_handler_pipeline_metadata(handler_function, **{field_name: components})
        return target

    return decorate
