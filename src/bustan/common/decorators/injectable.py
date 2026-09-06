"""Decorators for dependency injection."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import overload

from ...kernel.errors import InvalidProviderError
from ...kernel.utils import _get_metadata
from ..constants import BUSTAN_PROVIDER_ATTR
from ..tokens import token_identity
from ..types import ClassT, ProviderScope


@dataclass(frozen=True, slots=True)
class ProviderMetadata:
    """Static metadata captured from an @Injectable declaration.

    The declaration carries the lifetime and nothing else: a provider's token and the
    class it constructs are the decorated class itself, so there is no second copy of
    that identity to disagree with the class or to be rewritten after the fact.
    """

    scope: ProviderScope = ProviderScope.SINGLETON


def set_provider_metadata(provider_cls: ClassT, metadata: ProviderMetadata) -> ClassT:
    """Attach provider metadata to a class."""

    setattr(provider_cls, BUSTAN_PROVIDER_ATTR, metadata)
    return provider_cls


def get_provider_metadata(
    provider_cls: type[object], *, inherit: bool = False
) -> ProviderMetadata | None:
    """Retrieve provider metadata written on a class.

    Metadata describes the class the decorator was written on. A subclass has none of
    its own until it is decorated, so by default it is not read from a base class.
    """

    metadata = _get_metadata(provider_cls, BUSTAN_PROVIDER_ATTR, inherit=inherit)
    return metadata if isinstance(metadata, ProviderMetadata) else None


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
        raise InvalidProviderError(f"Unsupported provider scope: {scope!r}") from exc

    def decorate(provider_cls: ClassT) -> ClassT:
        if not isinstance(provider_cls, type):
            raise InvalidProviderError("@Injectable can only decorate classes")
        return set_provider_metadata(provider_cls, ProviderMetadata(scope=resolved_scope))

    if target is None:
        return decorate

    return decorate(target)


@dataclass(frozen=True, slots=True, eq=False)
class InjectMarker:
    """Annotated metadata that overrides a dependency token.

    Two markers are the same marker only when they name the same token, where sameness
    takes the token's type as well as its value. ``Annotated`` memoizes a subscription
    on its arguments, so a marker that compared equal to a marker over a different type
    would hand both annotations one object carrying one token, and the second parameter
    would silently receive the first one's provider.
    """

    token: object

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, InjectMarker):
            return NotImplemented
        return token_identity(self.token) == token_identity(other.token)

    def __hash__(self) -> int:
        return hash(token_identity(self.token))


@dataclass(frozen=True, slots=True)
class OptionalDependencyMarker:
    """Annotated metadata that allows missing provider dependencies."""


def Inject(token: object) -> InjectMarker:
    """Mark an ``Annotated`` dependency to resolve from an explicit token."""

    return InjectMarker(token=token)


def OptionalDep() -> OptionalDependencyMarker:
    """Mark an ``Annotated`` dependency as optional without shadowing ``typing.Optional``."""

    return OptionalDependencyMarker()
