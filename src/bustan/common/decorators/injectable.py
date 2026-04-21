"""Decorators for dependency injection."""

from __future__ import annotations

from collections.abc import Callable
from typing import overload

from ...core.errors import InvalidProviderError
from ..constants import BUSTAN_PROVIDER_ATTR
from ..types import ClassT, ProviderScope


@overload
def Injectable(
    target: ClassT, *, scope: ProviderScope | str = ProviderScope.SINGLETON
) -> ClassT: ...


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
        # We re-raise from InvalidProviderError if it exists, otherwise use a generic TypeError
        # until the full core/errors migration is complete if needed.
        raise InvalidProviderError(f"Unsupported provider scope: {scope!r}") from exc

    def decorate(provider_cls: ClassT) -> ClassT:
        if not isinstance(provider_cls, type):
            raise InvalidProviderError("@Injectable can only decorate classes")
        setattr(
            provider_cls,
            BUSTAN_PROVIDER_ATTR,
            {
                "scope": resolved_scope,
                "token": provider_cls,
                "use_class": provider_cls,
            },
        )
        return provider_cls

    if target is None:
        return decorate

    return decorate(target)
