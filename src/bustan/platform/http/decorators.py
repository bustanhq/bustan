"""Decorators for HTTP controllers and routes."""

from __future__ import annotations

from collections.abc import Callable
from types import FunctionType
from typing import TypeVar

from ...core.errors import (
    InvalidControllerError,
    RouteDefinitionError,
)
from ...core.utils import _unwrap_handler
from .metadata import (
    ControllerMetadata,
    RouteMetadata,
    get_route_metadata,
    normalize_controller_prefix,
    normalize_route_path,
    set_controller_metadata,
    set_route_metadata,
)

ClassT = TypeVar("ClassT", bound=type[object])
FunctionT = TypeVar("FunctionT", bound=FunctionType)


def Controller(prefix: str = "") -> Callable[[ClassT], ClassT]:
    """Attach controller metadata to a class."""

    controller_metadata = ControllerMetadata(prefix=normalize_controller_prefix(prefix))

    def decorate(controller_cls: ClassT) -> ClassT:
        if not isinstance(controller_cls, type):
            raise InvalidControllerError("@Controller can only decorate classes")
        return set_controller_metadata(controller_cls, controller_metadata)

    return decorate


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


def _normalize_method(method: str) -> str:
    """Validate and normalize an HTTP method string."""
    if not isinstance(method, str):
        raise RouteDefinitionError("Route method must be a string")

    normalized_method = method.strip().upper()
    if not normalized_method:
        raise RouteDefinitionError("Route method cannot be empty")

    if not all(character.isalpha() or character == "-" for character in normalized_method):
        raise RouteDefinitionError(f"Route method contains invalid characters: {method!r}")

    return normalized_method
