"""Internal utility functions shared across the bustan package."""

from __future__ import annotations

from enum import Enum
from types import FunctionType

from .ioc.tokens import InjectionToken
from .module.dynamic import DynamicModule

# What a value of one of these types prints is the value itself and nothing it was
# handed, so a token written as one of them prints as its declaration wrote it. Every
# other object prints what it holds - a module registration prints the providers it was
# built with, which for a configuration module is the whole resolved environment - and
# so has no display name of its own.
_SELF_DESCRIBING_TYPES = (str, bytes, int, float, complex, Enum)


def _qualname(target: object) -> str:
    """Return the dotted name of a class, or the declaration as it was written.

    This names the subject of an error raised while a declaration is being validated,
    where echoing what the author wrote is what makes the message actionable. It is not
    the name to print in a surface an application hands to its own callers: use
    ``_display_name`` there, which never prints what an object holds.
    """
    if isinstance(target, type):
        return f"{target.__module__}.{target.__qualname__}"

    # A registration key is recognised by the two fields that identify it rather than by
    # its type, so a stand-in for one is named the way the key it stands for is named.
    if hasattr(target, "module") and hasattr(target, "instance_id"):
        return f"{_qualname(target.module)}[{target.instance_id}]"

    if isinstance(target, DynamicModule):
        return f"{_qualname(target.module)} (dynamic)"

    return repr(target)


def _display_name(target: object) -> str:
    """Return a short name for a class, a module registration or a provider token.

    A name says what something is called and never what it holds, because it is printed
    where a value must not go: a message a caller can see, and the read-only inspection
    surface an application can expose to any caller of its own. So a module built by a
    factory is named by the class behind it, a token by the name its declaration gave
    it, and an object with no name of its own by the kind of thing it is.
    """
    if isinstance(target, type):
        return target.__name__

    if hasattr(target, "module") and hasattr(target, "instance_id"):
        return f"{_display_name(target.module)}[{target.instance_id}]"

    # A registration that has not been compiled has no index to be told apart by yet.
    if isinstance(target, DynamicModule):
        return f"{_display_name(target.module)} (dynamic)"

    # A token carries the name it was built with and nothing else, so it is safe to
    # print in full. A name that is itself a secret is one the declaration chose.
    if isinstance(target, InjectionToken):
        return f"InjectionToken({target.name!r})"

    if target is None or isinstance(target, _SELF_DESCRIBING_TYPES):
        return repr(target)

    return f"<{_display_name(type(target))}>"


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


def _get_metadata(
    target: type[object] | object, attribute_name: str, *, inherit: bool
) -> object | None:
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
