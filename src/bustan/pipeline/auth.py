"""Authentication contracts for compiled policy execution."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..kernel.ioc.tokens import InjectionToken
from .context import ExecutionContext


@runtime_checkable
class Principal(Protocol):
    """The caller a request is being served for: who they are, and what they may do."""

    id: str
    roles: tuple[str, ...]
    permissions: tuple[str, ...]


@runtime_checkable
class Authenticator(Protocol):
    """Identifies the caller behind one request, answering None when it cannot."""

    async def authenticate(self, context: ExecutionContext) -> Principal | None:
        pass


AUTHENTICATOR_REGISTRY = InjectionToken[dict[str, Authenticator]]("AUTHENTICATOR_REGISTRY")


__all__ = ("AUTHENTICATOR_REGISTRY", "Authenticator", "Principal")
