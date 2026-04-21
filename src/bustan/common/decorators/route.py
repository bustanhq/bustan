"""Decorators for HTTP routes."""

from __future__ import annotations

from typing import TypeVar
from types import FunctionType
from collections.abc import Callable

from ...core.errors import RouteDefinitionError
from ...core.utils import _normalize_path, _unwrap_handler
from ..constants import BUSTAN_ROUTE_ATTR
from ..types import RouteMetadata

FunctionT = TypeVar("FunctionT", bound=FunctionType)


def Route(method: str, path: str = "/") -> Callable[[FunctionT], FunctionT]:
    """Attach HTTP route metadata to a handler function."""

    normalized_method = _normalize_method(method)
    normalized_path = _normalize_route_path(path)

    def decorate(handler: FunctionT) -> FunctionT:
        handler_function = _unwrap_handler(handler)
        if handler_function is None:
            raise RouteDefinitionError("Route decorators can only decorate callables")

        # Check for existing metadata by looking at the attribute
        existing_route = getattr(handler_function, BUSTAN_ROUTE_ATTR, None)
        if existing_route is not None:
            raise RouteDefinitionError(
                f"{handler_function.__qualname__} already has route metadata for "
                f"{existing_route.method} {existing_route.path}"
            )

        setattr(
            handler_function,
            BUSTAN_ROUTE_ATTR,
            RouteMetadata(
                method=normalized_method,
                path=normalized_path,
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


def _normalize_route_path(path: str) -> str:
    """Normalize route paths into the canonical stored form."""
    normalized_path = _normalize_path(path, allow_empty=False, kind="route path")
    return normalized_path or "/"
