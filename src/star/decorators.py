"""Public decorators used to declare modules, providers, controllers, and routes."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from types import FunctionType
from typing import TypeVar, cast, overload

from .errors import (
    InvalidControllerError,
    InvalidModuleError,
    InvalidPipelineError,
    InvalidProviderError,
    RouteDefinitionError,
)
from .metadata import (
    ControllerMetadata,
    ModuleMetadata,
    ProviderMetadata,
    ProviderScope,
    RouteMetadata,
    extend_controller_pipeline_metadata,
    extend_handler_pipeline_metadata,
    get_route_metadata,
    normalize_controller_prefix,
    normalize_route_path,
    set_controller_metadata,
    set_module_metadata,
    set_provider_metadata,
    set_route_metadata,
)

ClassT = TypeVar("ClassT", bound=type[object])
FunctionT = TypeVar("FunctionT", bound=FunctionType)
DecoratedT = TypeVar("DecoratedT", bound=object)


def module(
    *,
    imports: Iterable[type[object]] | None = None,
    controllers: Iterable[type[object]] | None = None,
    providers: Iterable[type[object]] | None = None,
    exports: Iterable[type[object]] | None = None,
) -> Callable[[ClassT], ClassT]:
    """Attach module metadata to a class without performing registration."""

    module_metadata = ModuleMetadata(
        imports=_coerce_tuple(imports, field_name="imports"),
        controllers=_coerce_tuple(controllers, field_name="controllers"),
        providers=_coerce_tuple(providers, field_name="providers"),
        exports=_coerce_tuple(exports, field_name="exports"),
    )

    def decorate(module_cls: ClassT) -> ClassT:
        if not isinstance(module_cls, type):
            raise InvalidModuleError("@module can only decorate classes")
        return set_module_metadata(module_cls, module_metadata)

    return decorate


def controller(prefix: str = "") -> Callable[[ClassT], ClassT]:
    """Attach controller metadata to a class."""

    controller_metadata = ControllerMetadata(prefix=normalize_controller_prefix(prefix))

    def decorate(controller_cls: ClassT) -> ClassT:
        if not isinstance(controller_cls, type):
            raise InvalidControllerError("@controller can only decorate classes")
        return set_controller_metadata(controller_cls, controller_metadata)

    return decorate


@overload
def injectable(target: ClassT, *, scope: ProviderScope | str = ProviderScope.SINGLETON) -> ClassT: ...


@overload
def injectable(
    target: None = None,
    *,
    scope: ProviderScope | str = ProviderScope.SINGLETON,
) -> Callable[[ClassT], ClassT]: ...


def injectable(
    target: ClassT | None = None,
    *,
    scope: ProviderScope | str = ProviderScope.SINGLETON,
) -> ClassT | Callable[[ClassT], ClassT]:
    """Mark a class as a DI-managed provider with the selected scope."""

    try:
        resolved_scope = ProviderScope(scope)
    except ValueError as exc:
        raise InvalidProviderError(f"Unsupported provider scope: {scope!r}") from exc

    def decorate(provider_cls: ClassT) -> ClassT:
        if not isinstance(provider_cls, type):
            raise InvalidProviderError("@injectable can only decorate classes")
        return set_provider_metadata(provider_cls, ProviderMetadata(scope=resolved_scope))

    if target is None:
        return decorate

    return decorate(target)


def route(method: str, path: str = "/") -> Callable[[FunctionT], FunctionT]:
    """Attach HTTP route metadata to a handler function."""

    normalized_method = _normalize_method(method)
    route_metadata = RouteMetadata(
        method=normalized_method,
        path=normalize_route_path(path),
        name="",
    )

    def decorate(handler: FunctionT) -> FunctionT:
        handler_function = _unwrap_handler(handler)
        if handler_function is None:
            raise RouteDefinitionError("Route decorators can only decorate callables")

        existing_route = get_route_metadata(handler_function)
        if existing_route is not None:
            raise RouteDefinitionError(
                f"{handler_function.__qualname__} already has route metadata for "
                f"{existing_route.method} {existing_route.path}"
            )

        set_route_metadata(
            handler_function,
            RouteMetadata(
                method=route_metadata.method,
                path=route_metadata.path,
                name=handler_function.__name__,
            ),
        )
        return handler

    return decorate


def get(path: str = "/") -> Callable[[FunctionT], FunctionT]:
    """Return a decorator that registers a GET route."""

    return route("GET", path)


def post(path: str = "/") -> Callable[[FunctionT], FunctionT]:
    """Return a decorator that registers a POST route."""

    return route("POST", path)


def put(path: str = "/") -> Callable[[FunctionT], FunctionT]:
    """Return a decorator that registers a PUT route."""

    return route("PUT", path)


def patch(path: str = "/") -> Callable[[FunctionT], FunctionT]:
    """Return a decorator that registers a PATCH route."""

    return route("PATCH", path)


def delete(path: str = "/") -> Callable[[FunctionT], FunctionT]:
    """Return a decorator that registers a DELETE route."""

    return route("DELETE", path)


def use_guards(*guards: object) -> Callable[[DecoratedT], DecoratedT]:
    """Attach one or more guards to a controller or handler."""

    return _pipeline_decorator("guards", guards)


def use_pipes(*pipes: object) -> Callable[[DecoratedT], DecoratedT]:
    """Attach one or more pipes to a controller or handler."""

    return _pipeline_decorator("pipes", pipes)


def use_interceptors(*interceptors: object) -> Callable[[DecoratedT], DecoratedT]:
    """Attach one or more interceptors to a controller or handler."""

    return _pipeline_decorator("interceptors", interceptors)


def use_filters(*filters: object) -> Callable[[DecoratedT], DecoratedT]:
    """Attach one or more exception filters to a controller or handler."""

    return _pipeline_decorator("filters", filters)


def _coerce_tuple(
    values: Iterable[type[object]] | None,
    *,
    field_name: str,
) -> tuple[type[object], ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes)):
        raise InvalidModuleError(f"Module {field_name} must be an iterable of objects")

    try:
        return tuple(values)
    except TypeError as exc:
        raise InvalidModuleError(f"Module {field_name} must be an iterable of objects") from exc


def _normalize_method(method: str) -> str:
    if not isinstance(method, str):
        raise RouteDefinitionError("Route method must be a string")

    normalized_method = method.strip().upper()
    if not normalized_method:
        raise RouteDefinitionError("Route method cannot be empty")

    if not all(character.isalpha() or character == "-" for character in normalized_method):
        raise RouteDefinitionError(f"Route method contains invalid characters: {method!r}")

    return normalized_method


def _unwrap_handler(handler: object) -> FunctionType | None:
    if isinstance(handler, (staticmethod, classmethod)):
        handler = handler.__func__
    return handler if isinstance(handler, FunctionType) else None


def _pipeline_decorator(
    field_name: str,
    components: tuple[object, ...],
) -> Callable[[DecoratedT], DecoratedT]:
    if not components:
        raise InvalidPipelineError(f"@use_{field_name} requires at least one component")

    def decorate(target: DecoratedT) -> DecoratedT:
        if isinstance(target, type):
            return cast(
                DecoratedT,
                extend_controller_pipeline_metadata(target, **{field_name: components}),
            )

        handler_function = _unwrap_handler(target)
        if handler_function is None:
            raise InvalidPipelineError(
                f"@use_{field_name} can only decorate controller classes or handler callables"
            )

        extend_handler_pipeline_metadata(handler_function, **{field_name: components})
        return target

    return decorate