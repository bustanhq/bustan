"""Decorators for HTTP controllers."""

from __future__ import annotations

from collections.abc import Callable

from ...core.errors import InvalidControllerError, RouteDefinitionError
from ...core.utils import _normalize_path
from ..constants import BUSTAN_CONTROLLER_ATTR
from ..types import ClassT, ControllerMetadata, ProviderScope


def Controller(
    prefix: str = "",
    *,
    scope: ProviderScope | str = ProviderScope.SINGLETON,
    version: str | list[str] | None = None,
) -> Callable[[ClassT], ClassT]:
    """Attach controller metadata to a class."""

    try:
        resolved_scope = ProviderScope(scope)
    except ValueError as exc:
        raise InvalidControllerError(f"Unsupported controller scope: {scope!r}") from exc

    controller_metadata = ControllerMetadata(
        prefix=_normalize_controller_prefix(prefix),
        scope=resolved_scope,
        version=version,
    )

    def decorate(controller_cls: ClassT) -> ClassT:
        if not isinstance(controller_cls, type):
            raise InvalidControllerError("@Controller can only decorate classes")
        setattr(controller_cls, BUSTAN_CONTROLLER_ATTR, controller_metadata)
        return controller_cls

    return decorate


def _normalize_controller_prefix(prefix: str) -> str:
    """Normalize controller prefixes into the canonical stored form."""
    try:
        return _normalize_path(prefix, allow_empty=True, kind="controller prefix")
    except RouteDefinitionError as exc:
        raise InvalidControllerError(str(exc)) from exc
