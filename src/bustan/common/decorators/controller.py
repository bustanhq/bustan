"""Decorators for HTTP controllers."""

from __future__ import annotations

from collections.abc import Callable

from ...core.errors import InvalidControllerError, RouteDefinitionError
from ...core.utils import _normalize_path
from ..constants import BUSTAN_CONTROLLER_ATTR
from ..types import ClassT, ControllerMetadata, HostInput, ProviderScope, normalize_hosts


def Controller(
    prefix: str = "",
    *,
    scope: ProviderScope | str = ProviderScope.SINGLETON,
    version: str | list[str] | None = None,
    host: HostInput | None = None,
    hosts: HostInput | None = None,
    binding_mode: str = "infer",
    validation_mode: str = "auto",
    validate_custom_decorators: bool = False,
) -> Callable[[ClassT], ClassT]:
    """Attach controller metadata to a class."""

    try:
        resolved_scope = ProviderScope(scope)
    except ValueError as exc:
        raise InvalidControllerError(f"Unsupported controller scope: {scope!r}") from exc

    resolved_hosts = _resolve_hosts(host=host, hosts=hosts)

    controller_metadata = ControllerMetadata(
        prefix=_normalize_controller_prefix(prefix),
        scope=resolved_scope,
        version=version,
        hosts=resolved_hosts,
        binding_mode=binding_mode,
        validation_mode=validation_mode,
        validate_custom_decorators=validate_custom_decorators,
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


def _resolve_hosts(*, host: HostInput | None, hosts: HostInput | None) -> tuple[str, ...]:
    if host is not None and hosts is not None:
        raise InvalidControllerError("Use either 'host' or 'hosts', not both")

    try:
        return normalize_hosts(host if host is not None else hosts)
    except ValueError as exc:
        raise InvalidControllerError(str(exc)) from exc
