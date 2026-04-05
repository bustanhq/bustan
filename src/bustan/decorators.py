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
    ClassProviderDef,
    ControllerMetadata,
    ExistingProviderDef,
    FactoryProviderDef,
    ModuleMetadata,
    ProviderDef,
    ProviderMetadata,
    ProviderScope,
    RouteMetadata,
    ValueProviderDef,
    extend_controller_pipeline_metadata,
    extend_handler_pipeline_metadata,
    get_provider_metadata,
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


def Module(
    *,
    imports: Iterable[type[object]] | None = None,
    controllers: Iterable[type[object]] | None = None,
    providers: Iterable[type[object] | dict[str, object] | ProviderDef] | None = None,
    exports: Iterable[object] | None = None,
) -> Callable[[ClassT], ClassT]:
    """Attach module metadata to a class without performing registration."""

    module_metadata = ModuleMetadata(
        imports=_coerce_tuple(imports, field_name="imports"),
        controllers=_coerce_tuple(controllers, field_name="controllers"),
        providers=_normalize_providers(providers),
        exports=_coerce_tuple(exports, field_name="exports"),
    )

    def decorate(module_cls: ClassT) -> ClassT:
        if not isinstance(module_cls, type):
            raise InvalidModuleError("@Module can only decorate classes")
        return set_module_metadata(module_cls, module_metadata)

    return decorate


def Controller(prefix: str = "") -> Callable[[ClassT], ClassT]:
    """Attach controller metadata to a class."""

    controller_metadata = ControllerMetadata(prefix=normalize_controller_prefix(prefix))

    def decorate(controller_cls: ClassT) -> ClassT:
        if not isinstance(controller_cls, type):
            raise InvalidControllerError("@Controller can only decorate classes")
        return set_controller_metadata(controller_cls, controller_metadata)

    return decorate


@overload
def Injectable(target: ClassT, *, scope: ProviderScope | str = ProviderScope.SINGLETON) -> ClassT: ...


@overload
def Injectable(
    target: None = None,
    *,
    scope: ProviderScope | str = ProviderScope.SINGLETON,
) -> Callable[[ClassT], ClassT]: ...


def Injectable(
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
            raise InvalidProviderError("@Injectable can only decorate classes")
        return set_provider_metadata(provider_cls, ProviderMetadata(scope=resolved_scope))

    if target is None:
        return decorate

    return decorate(target)


def Route(method: str, path: str = "/") -> Callable[[FunctionT], FunctionT]:
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


def Get(path: str = "/") -> Callable[[FunctionT], FunctionT]:
    """Return a decorator that registers a GET route."""

    return Route("GET", path)


def Post(path: str = "/") -> Callable[[FunctionT], FunctionT]:
    """Return a decorator that registers a POST route."""

    return Route("POST", path)


def Put(path: str = "/") -> Callable[[FunctionT], FunctionT]:
    """Return a decorator that registers a PUT route."""

    return Route("PUT", path)


def Patch(path: str = "/") -> Callable[[FunctionT], FunctionT]:
    """Return a decorator that registers a PATCH route."""

    return Route("PATCH", path)


def Delete(path: str = "/") -> Callable[[FunctionT], FunctionT]:
    """Return a decorator that registers a DELETE route."""

    return Route("DELETE", path)


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


def _coerce_tuple(
    values: Iterable[object] | None,
    *,
    field_name: str,
) -> tuple[object, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes)):
        raise InvalidModuleError(f"Module {field_name} must be an iterable of objects")

    try:
        return tuple(values)
    except TypeError as exc:
        raise InvalidModuleError(f"Module {field_name} must be an iterable of objects") from exc


def _normalize_providers(
    entries: Iterable[type[object] | dict[str, object] | ProviderDef] | None,
) -> tuple[ProviderDef, ...]:
    """Normalize a raw providers list into a tuple of ProviderDef objects."""

    if entries is None:
        return ()
    if isinstance(entries, (str, bytes)):
        raise InvalidModuleError("Module providers must be an iterable of objects")

    try:
        raw = tuple(entries)
    except TypeError as exc:
        raise InvalidModuleError("Module providers must be an iterable of objects") from exc

    return tuple(_normalize_provider_def(entry) for entry in raw)


def _normalize_provider_def(
    entry: type[object] | dict[str, object] | ProviderDef,
) -> ProviderDef:
    """Convert a class, dict, or ProviderDef into a canonical ProviderDef."""

    if isinstance(entry, (ClassProviderDef, FactoryProviderDef, ValueProviderDef, ExistingProviderDef)):
        return entry

    if isinstance(entry, type):
        provider_metadata = get_provider_metadata(entry)
        scope = provider_metadata.scope if provider_metadata is not None else ProviderScope.SINGLETON
        return ClassProviderDef(provide=entry, use_class=entry, scope=scope)

    if isinstance(entry, dict):
        return _normalize_dict_provider_def(entry)

    raise InvalidProviderError(
        f"Invalid provider entry: {entry!r}. Expected a class, dict, or ProviderDef."
    )


def _normalize_dict_provider_def(d: dict[str, object]) -> ProviderDef:
    """Parse a dict-form provider declaration into a ProviderDef."""

    if "provide" not in d:
        raise InvalidProviderError("Provider dict must include a 'provide' key")

    token = d["provide"]

    if "use_value" in d:
        return ValueProviderDef(provide=token, use_value=d["use_value"])

    if "use_existing" in d:
        return ExistingProviderDef(provide=token, use_existing=d["use_existing"])

    if "use_factory" in d:
        scope = _parse_provider_scope(d.get("scope", ProviderScope.SINGLETON))
        inject_raw = d.get("inject", ())
        if isinstance(inject_raw, (str, bytes)):
            raise InvalidProviderError("Provider dict 'inject' must be an iterable of tokens")
        try:
            inject: tuple[object, ...] = tuple(inject_raw)  # type: ignore[arg-type]
        except TypeError as exc:
            raise InvalidProviderError("Provider dict 'inject' must be an iterable of tokens") from exc
        factory = d["use_factory"]
        if not callable(factory):
            raise InvalidProviderError(
                f"Provider dict 'use_factory' must be callable, got {factory!r}"
            )
        return FactoryProviderDef(provide=token, use_factory=factory, inject=inject, scope=scope)

    if "use_class" in d:
        scope = _parse_provider_scope(d.get("scope", ProviderScope.SINGLETON))
        use_class = d["use_class"]
        if not isinstance(use_class, type):
            raise InvalidProviderError(
                f"Provider dict 'use_class' must be a class, got {use_class!r}"
            )
        return ClassProviderDef(provide=token, use_class=use_class, scope=scope)

    raise InvalidProviderError(
        "Provider dict must include one of: 'use_class', 'use_factory', 'use_value', 'use_existing'"
    )


def _parse_provider_scope(scope_value: object) -> ProviderScope:
    if isinstance(scope_value, ProviderScope):
        return scope_value
    try:
        return ProviderScope(scope_value)
    except ValueError as exc:
        raise InvalidProviderError(f"Unsupported provider scope: {scope_value!r}") from exc


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