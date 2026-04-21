"""Typed tokens for dependency injection."""

from __future__ import annotations

from typing import Generic

from ...common.types import T


class InjectionToken(Generic[T]):
    """A typed token representing a dependency for injection."""

    def __init__(self, name: str):
        self.name = name

    def __repr__(self) -> str:
        return f"InjectionToken({self.name!r})"
