"""Internal utility functions shared across the bustan package."""

from __future__ import annotations

from types import FunctionType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .module.dynamic import ModuleInstanceKey  # noqa: F401


def _qualname(target: object) -> str:
    """Return the qualified name of a class or function, or its repr."""
    if isinstance(target, type):
        return f"{target.__module__}.{target.__qualname__}"

    # Avoid circular import by checking attribute existence
    if hasattr(target, "module") and hasattr(target, "instance_id"):
        return f"{_qualname(target.module)}[{target.instance_id}]"

    return repr(target)


def _display_name(target: object) -> str:
    """Return a human-readable name for a class or its repr."""
    if isinstance(target, type):
        return target.__name__

    if hasattr(target, "module") and hasattr(target, "instance_id"):
        return f"{_display_name(target.module)}[{target.instance_id}]"

    return repr(target)


def _join_paths(prefix: str, path: str) -> str:
    """Join a controller prefix and route path into a canonical form."""
    if not prefix:
        return path
    if path == "/":
        return prefix
    return f"{prefix}{path}"


def _unwrap_handler(handler: object) -> FunctionType | None:
    """Unwrap staticmethod or classmethod to get the underlying function."""
    if isinstance(handler, (staticmethod, classmethod)):
        handler = handler.__func__
    return handler if isinstance(handler, FunctionType) else None


def _get_metadata(target: type[object] | object, attribute_name: str, *, inherit: bool) -> object | None:
    """Retrieve metadata from a class, optionally inheriting from base classes."""
    if inherit:
        return getattr(target, attribute_name, None)
    return getattr(target, "__dict__", {}).get(attribute_name)


def _normalize_path(path: str, *, allow_empty: bool, kind: str) -> str:
    """Normalize a URL path segment or prefix."""
    from .errors import RouteDefinitionError

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
