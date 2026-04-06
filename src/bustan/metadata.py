"""Typed metadata storage used by decorators and bootstrap code."""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from enum import StrEnum
from types import FunctionType
from typing import Any, TypeVar, cast

from .errors import InvalidControllerError, RouteDefinitionError
from .utils import _unwrap_handler

MODULE_METADATA_ATTR = "__bustan_module_metadata__"
CONTROLLER_METADATA_ATTR = "__bustan_controller_metadata__"
ROUTE_METADATA_ATTR = "__bustan_route_metadata__"
CONTROLLER_PIPELINE_ATTR = "__bustan_controller_pipeline_metadata__"
HANDLER_PIPELINE_ATTR = "__bustan_handler_pipeline_metadata__"
BUSTAN_PROVIDER_ATTR = "__bustan_provider__"

ClassT = TypeVar("ClassT", bound=type[object])
FunctionT = TypeVar("FunctionT", bound=FunctionType)


@dataclass(frozen=True, slots=True)
class ModuleInstanceKey:
    """Unique identity for one dynamic registration of a module."""

    module: type[object]
    instance_id: str


ModuleKey = type[object] | ModuleInstanceKey


@dataclass(frozen=True, slots=True)
class DynamicModule:
    """Metadata overlay that compiles into a unique module instance."""

    module: type[object]
    providers: tuple[object | dict[str, Any], ...] = ()
    imports: tuple[type[object] | DynamicModule, ...] = ()
    controllers: tuple[type[object], ...] = ()
    exports: tuple[object, ...] = ()


class ProviderScope(StrEnum):
    """Supported provider lifetimes."""

    SINGLETON = "singleton"
    TRANSIENT = "transient"
    REQUEST = "request"


@dataclass(frozen=True, slots=True)
class Binding:
    """Normalized dependency injection binding."""

    token: object
    declaring_module: ModuleKey
    resolver_kind: str  # class | factory | value | existing
    target: object
    scope: ProviderScope


@dataclass(frozen=True, slots=True)
class ModuleMetadata:
    """Static metadata captured from a @Module declaration."""

    imports: tuple[type[object] | DynamicModule, ...] = ()
    controllers: tuple[type[object], ...] = ()
    providers: tuple[object | dict[str, Any], ...] = ()
    exports: tuple[object, ...] = ()


@dataclass(frozen=True, slots=True)
class ControllerMetadata:
    """Static metadata captured from a @Controller declaration."""

    prefix: str = ""


@dataclass(frozen=True, slots=True)
class RouteMetadata:
    """Static metadata captured from an HTTP method decorator."""

    method: str
    path: str
    name: str


@dataclass(frozen=True, slots=True)
class ControllerRouteDefinition:
    """Resolved route entry for one controller handler."""

    handler_name: str
    handler: FunctionType
    route: RouteMetadata


@dataclass(frozen=True, slots=True)
class PipelineMetadata:
    """Merged pipeline component declarations for a controller or handler."""

    guards: tuple[object, ...] = ()
    pipes: tuple[object, ...] = ()
    interceptors: tuple[object, ...] = ()
    filters: tuple[object, ...] = ()


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


def set_module_metadata(module_cls: ClassT, metadata: ModuleMetadata) -> ClassT:
    setattr(module_cls, MODULE_METADATA_ATTR, metadata)
    return module_cls


def get_module_metadata(
    module_cls: type[object], *, inherit: bool = False
) -> ModuleMetadata | None:
    metadata = _get_metadata(module_cls, MODULE_METADATA_ATTR, inherit=inherit)
    return metadata if isinstance(metadata, ModuleMetadata) else None


def set_controller_metadata(controller_cls: ClassT, metadata: ControllerMetadata) -> ClassT:
    setattr(controller_cls, CONTROLLER_METADATA_ATTR, metadata)
    return controller_cls


def get_controller_metadata(
    controller_cls: type[object], *, inherit: bool = False
) -> ControllerMetadata | None:
    metadata = _get_metadata(controller_cls, CONTROLLER_METADATA_ATTR, inherit=inherit)
    return metadata if isinstance(metadata, ControllerMetadata) else None


def set_controller_pipeline_metadata(controller_cls: ClassT, metadata: PipelineMetadata) -> ClassT:
    setattr(controller_cls, CONTROLLER_PIPELINE_ATTR, metadata)
    return controller_cls


def get_controller_pipeline_metadata(
    controller_cls: type[object], *, inherit: bool = False
) -> PipelineMetadata | None:
    metadata = _get_metadata(controller_cls, CONTROLLER_PIPELINE_ATTR, inherit=inherit)
    return metadata if isinstance(metadata, PipelineMetadata) else None


def set_route_metadata(handler: FunctionT, metadata: RouteMetadata) -> FunctionT:
    setattr(handler, ROUTE_METADATA_ATTR, metadata)
    return handler


def get_route_metadata(handler: object) -> RouteMetadata | None:
    unwrapped_handler = _unwrap_handler(handler)
    if unwrapped_handler is None:
        return None

    metadata = getattr(unwrapped_handler, ROUTE_METADATA_ATTR, None)
    return metadata if isinstance(metadata, RouteMetadata) else None


def set_handler_pipeline_metadata(handler: FunctionT, metadata: PipelineMetadata) -> FunctionT:
    setattr(handler, HANDLER_PIPELINE_ATTR, metadata)
    return handler


def get_handler_pipeline_metadata(handler: object) -> PipelineMetadata | None:
    unwrapped_handler = _unwrap_handler(handler)
    if unwrapped_handler is None:
        return None

    metadata = getattr(unwrapped_handler, HANDLER_PIPELINE_ATTR, None)
    return metadata if isinstance(metadata, PipelineMetadata) else None


def extend_controller_pipeline_metadata(
    controller_cls: ClassT,
    *,
    guards: tuple[object, ...] = (),
    pipes: tuple[object, ...] = (),
    interceptors: tuple[object, ...] = (),
    filters: tuple[object, ...] = (),
) -> ClassT:
    existing_metadata = get_controller_pipeline_metadata(controller_cls) or PipelineMetadata()
    merged_metadata = merge_pipeline_metadata(
        existing_metadata,
        PipelineMetadata(
            guards=guards,
            pipes=pipes,
            interceptors=interceptors,
            filters=filters,
        ),
    )
    return set_controller_pipeline_metadata(controller_cls, merged_metadata)


def extend_handler_pipeline_metadata(
    handler: FunctionT,
    *,
    guards: tuple[object, ...] = (),
    pipes: tuple[object, ...] = (),
    interceptors: tuple[object, ...] = (),
    filters: tuple[object, ...] = (),
) -> FunctionT:
    existing_metadata = get_handler_pipeline_metadata(handler) or PipelineMetadata()
    merged_metadata = merge_pipeline_metadata(
        existing_metadata,
        PipelineMetadata(
            guards=guards,
            pipes=pipes,
            interceptors=interceptors,
            filters=filters,
        ),
    )
    return set_handler_pipeline_metadata(handler, merged_metadata)


def merge_pipeline_metadata(*metadata_items: PipelineMetadata) -> PipelineMetadata:
    """Merge pipeline metadata while preserving declaration order."""

    guards: list[object] = []
    pipes: list[object] = []
    interceptors: list[object] = []
    filters: list[object] = []

    for metadata in metadata_items:
        guards.extend(metadata.guards)
        pipes.extend(metadata.pipes)
        interceptors.extend(metadata.interceptors)
        filters.extend(metadata.filters)

    return PipelineMetadata(
        guards=tuple(guards),
        pipes=tuple(pipes),
        interceptors=tuple(interceptors),
        filters=tuple(filters),
    )


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


def _normalize_path(path: str, *, allow_empty: bool, kind: str) -> str:
    if not isinstance(path, str):
        raise RouteDefinitionError(f"{kind.capitalize()} must be a string")

    normalized_path = path.strip()
    if not normalized_path:
        if allow_empty:
            return ""
        raise RouteDefinitionError(f"{kind.capitalize()} cannot be empty")

    if not normalized_path.startswith("/"):
        normalized_path = f"/{normalized_path}"

    if normalized_path != "/" and normalized_path.endswith("/"):
        normalized_path = normalized_path.rstrip("/")

    if allow_empty and normalized_path == "/":
        return ""

    return normalized_path


def _get_metadata(target: type[object], attribute_name: str, *, inherit: bool) -> object | None:
    if inherit:
        return getattr(target, attribute_name, None)
    return target.__dict__.get(attribute_name)


def normalize_provider(defn: object | dict[str, Any], declaring_module: ModuleKey) -> Binding:
    if inspect.isclass(defn):
        meta: dict[str, object] = getattr(defn, "__bustan_provider__", {})
        return Binding(
            token=meta.get("token", defn),
            declaring_module=declaring_module,
            resolver_kind="class",
            target=meta.get("use_class", defn),
            scope=ProviderScope(meta.get("scope", ProviderScope.SINGLETON)),
        )

    if isinstance(defn, dict):
        defn = cast(dict[str, Any], defn)
        token = defn.get("provide")
        if token is None:
            raise TypeError("Provider dict must provide a 'provide' key")

        scope = ProviderScope(defn.get("scope", ProviderScope.SINGLETON))

        if "use_class" in defn:
            return Binding(
                token=token,
                declaring_module=declaring_module,
                resolver_kind="class",
                target=defn["use_class"],
                scope=scope,
            )
        if "use_factory" in defn:
            inject = tuple(defn.get("inject", ()))
            # For factories, target can be the callable, but wait, Container will need inject
            # Let's say target stores (factory, inject).
            return Binding(
                token=token,
                declaring_module=declaring_module,
                resolver_kind="factory",
                target=(defn["use_factory"], inject),
                scope=scope,
            )
        if "use_value" in defn:
            return Binding(
                token=token,
                declaring_module=declaring_module,
                resolver_kind="value",
                target=defn["use_value"],
                scope=ProviderScope.SINGLETON,
            )
        if "use_existing" in defn:
            return Binding(
                token=token,
                declaring_module=declaring_module,
                resolver_kind="existing",
                target=defn["use_existing"],
                scope=ProviderScope.TRANSIENT,
            )

        raise TypeError(
            "Provider dict must have one of: use_class, use_factory, use_value, use_existing"
        )

    raise TypeError(f"Invalid provider definition: {defn!r}")
