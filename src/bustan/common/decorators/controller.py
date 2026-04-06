"""Decorators for HTTP controllers."""

from __future__ import annotations

from collections.abc import Callable

from ...core.errors import InvalidControllerError, RouteDefinitionError
from ...core.utils import _normalize_path
from ..constants import BUSTAN_CONTROLLER_ATTR
from ..types import ClassT, ControllerMetadata


def Controller(prefix: str = "") -> Callable[[ClassT], ClassT]:
    """Attach controller metadata to a class."""

    controller_metadata = ControllerMetadata(prefix=_normalize_controller_prefix(prefix))

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
