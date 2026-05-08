"""Metadata and hook protocol definitions for the module lifecycle."""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Protocol, runtime_checkable


@runtime_checkable
class OnModuleInit(Protocol):
    """Protocol for components that run during module initialization."""

    def on_module_init(self) -> None | Awaitable[None]:
        pass


@runtime_checkable
class OnApplicationBootstrap(Protocol):
    """Protocol for components that run when the application starts."""

    def on_application_bootstrap(self) -> None | Awaitable[None]:
        pass


@runtime_checkable
class BeforeApplicationShutdown(Protocol):
    """Protocol for components that run before application shutdown begins."""

    def before_application_shutdown(self, signal: str | None) -> None | Awaitable[None]:
        pass


@runtime_checkable
class OnApplicationShutdown(Protocol):
    """Protocol for components that run during application shutdown."""

    def on_application_shutdown(self, signal: str | None) -> None | Awaitable[None]:
        pass


@runtime_checkable
class OnModuleDestroy(Protocol):
    """Protocol for components that run when a module is torn down."""

    def on_module_destroy(self) -> None | Awaitable[None]:
        pass

LifecycleHookName: tuple[str, ...] = (
    "on_module_init",
    "on_application_bootstrap",
    "before_application_shutdown",
    "on_application_shutdown",
    "on_module_destroy",
)
