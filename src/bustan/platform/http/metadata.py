"""Metadata structures for HTTP controllers and routes."""

from __future__ import annotations

from dataclasses import dataclass
from types import FunctionType
from typing import TypeVar

from ...common.constants import (
    BUSTAN_CONTROLLER_ATTR as CONTROLLER_METADATA_ATTR,
    BUSTAN_ROUTE_ATTR as ROUTE_METADATA_ATTR,
)

from ...common.types import (
    ControllerMetadata,
    RouteMetadata,
)

from ...core.errors import InvalidControllerError, RouteDefinitionError
from ...core.utils import _get_metadata, _normalize_path, _unwrap_handler


ClassT = TypeVar("ClassT", bound=type[object])
FunctionT = TypeVar("FunctionT", bound=FunctionType)


@dataclass(frozen=True, slots=True)
class ControllerRouteDefinition:
    """Resolved route entry for one controller handler."""

    handler_name: str
    handler: FunctionType
    route: RouteMetadata


def normalize_controller_prefix(prefix: str) -> str:
    """Normalize controller prefixes into the canonical stored form."""

    try:
        return _normalize_path(prefix, allow_empty=True, kind="controller prefix")
    except RouteDefinitionError as exc:
        raise InvalidControllerError(str(exc)) from exc


def normalize_route_path(path: str) -> str:
    """Normalize route paths into the canonical stored form."""

    normalized_path = _normalize_path(path, allow_empty=False, kind="route path")
    return normalized_path or "/"


def set_controller_metadata(controller_cls: ClassT, metadata: ControllerMetadata) -> ClassT:
    setattr(controller_cls, CONTROLLER_METADATA_ATTR, metadata)
    return controller_cls


def get_controller_metadata(
    controller_cls: type[object], *, inherit: bool = False
) -> ControllerMetadata | None:
    metadata = _get_metadata(controller_cls, CONTROLLER_METADATA_ATTR, inherit=inherit)
    return metadata if isinstance(metadata, ControllerMetadata) else None


def set_route_metadata(handler: FunctionT, metadata: RouteMetadata) -> FunctionT:
    setattr(handler, ROUTE_METADATA_ATTR, metadata)
    return handler


def get_route_metadata(handler: object) -> RouteMetadata | None:
    unwrapped_handler = _unwrap_handler(handler)
    if unwrapped_handler is None:
        return None

    metadata = getattr(unwrapped_handler, ROUTE_METADATA_ATTR, None)
    return metadata if isinstance(metadata, RouteMetadata) else None


def iter_controller_routes(controller_cls: type[object]) -> tuple[ControllerRouteDefinition, ...]:
    """Return route definitions discovered across a controller's MRO."""

    resolved_members: dict[str, object] = {}
    for base_cls in reversed(controller_cls.__mro__):
        if base_cls is object:
            continue
        resolved_members.update(base_cls.__dict__)

    routes: list[ControllerRouteDefinition] = []
    for member_name, member in resolved_members.items():
        handler = _unwrap_handler(member)
        if handler is None:
            continue

        route_metadata = get_route_metadata(handler)
        if route_metadata is None:
            continue

        routes.append(
            ControllerRouteDefinition(
                handler_name=member_name,
                handler=handler,
                route=route_metadata,
            )
        )

    return tuple(routes)
