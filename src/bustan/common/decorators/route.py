"""Decorators for HTTP routes."""

from __future__ import annotations

from typing import TypeVar
from types import FunctionType
from collections.abc import Callable

from ...core.errors import RouteDefinitionError
from ...core.utils import _normalize_path, _unwrap_handler
from ..constants import BUSTAN_ROUTE_ATTR
from ..types import HostInput, RouteMetadata, normalize_hosts

FunctionT = TypeVar("FunctionT", bound=FunctionType)


def Route(
    method: str,
    path: str = "/",
    *,
    version: str | list[str] | None = None,
    host: HostInput | None = None,
    hosts: HostInput | None = None,
) -> Callable[[FunctionT], FunctionT]:
    """Attach HTTP route metadata to a handler function."""

    normalized_method = _normalize_method(method)
    normalized_path = _normalize_route_path(path)
    normalized_hosts = _resolve_hosts(host=host, hosts=hosts)

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
                version=version,
                hosts=normalized_hosts,
            ),
        )
        return handler

    return decorate


def Get(
    path: str = "/",
    *,
    version: str | list[str] | None = None,
    host: HostInput | None = None,
    hosts: HostInput | None = None,
) -> Callable[[FunctionT], FunctionT]:
    """Return a decorator that registers a GET route."""
    return Route("GET", path, version=version, host=host, hosts=hosts)


def Post(
    path: str = "/",
    *,
    version: str | list[str] | None = None,
    host: HostInput | None = None,
    hosts: HostInput | None = None,
) -> Callable[[FunctionT], FunctionT]:
    """Return a decorator that registers a POST route."""
    return Route("POST", path, version=version, host=host, hosts=hosts)


def Put(
    path: str = "/",
    *,
    version: str | list[str] | None = None,
    host: HostInput | None = None,
    hosts: HostInput | None = None,
) -> Callable[[FunctionT], FunctionT]:
    """Return a decorator that registers a PUT route."""
    return Route("PUT", path, version=version, host=host, hosts=hosts)


def Patch(
    path: str = "/",
    *,
    version: str | list[str] | None = None,
    host: HostInput | None = None,
    hosts: HostInput | None = None,
) -> Callable[[FunctionT], FunctionT]:
    """Return a decorator that registers a PATCH route."""
    return Route("PATCH", path, version=version, host=host, hosts=hosts)


def Delete(
    path: str = "/",
    *,
    version: str | list[str] | None = None,
    host: HostInput | None = None,
    hosts: HostInput | None = None,
) -> Callable[[FunctionT], FunctionT]:
    """Return a decorator that registers a DELETE route."""
    return Route("DELETE", path, version=version, host=host, hosts=hosts)


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


def _resolve_hosts(*, host: HostInput | None, hosts: HostInput | None) -> tuple[str, ...]:
    if host is not None and hosts is not None:
        raise RouteDefinitionError("Use either 'host' or 'hosts', not both")

    try:
        return normalize_hosts(host if host is not None else hosts)
    except ValueError as exc:
        raise RouteDefinitionError(str(exc)) from exc
