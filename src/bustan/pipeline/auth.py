"""Authentication contracts for compiled policy execution."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..core.ioc.tokens import InjectionToken
from .context import ExecutionContext


@runtime_checkable
class Principal(Protocol):
    id: str
    roles: tuple[str, ...]
    permissions: tuple[str, ...]


@runtime_checkable
class Authenticator(Protocol):
    async def authenticate(self, context: ExecutionContext) -> Principal | None:
        pass


AUTHENTICATOR_REGISTRY = InjectionToken[dict[str, Authenticator]]("AUTHENTICATOR_REGISTRY")


__all__ = ("AUTHENTICATOR_REGISTRY", "Authenticator", "Principal")