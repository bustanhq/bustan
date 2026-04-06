"""Public application wrapper for Starlette with Bustan integration."""

from __future__ import annotations

from typing import cast, Callable
from collections.abc import Mapping

from starlette.applications import Starlette

from ..core.ioc.container import Container
from ..core.module.dynamic import ModuleKey


class Application:
    """A wrapper around Starlette that exposes the Bustan IoC container.

    This provides a clean interface for application-wide services and
    testing while delegating HTTP handling to the Starlette core.
    """

    def __init__(self, starlette_app: Starlette, container: Container) -> None:
        self._starlette_app = starlette_app
        self._container = container

    @property
    def starlette_app(self) -> Starlette:
        """Accessor for the underlying Starlette instance."""
        return self._starlette_app

    @property
    def container(self) -> Container:
        """Accessor for the underlying IoC container."""
        return self._container

    def override(self, token: object, value: object, *, module: ModuleKey | None = None) -> None:
        """Register a replacement object for a provider."""
        self._container.override(token, value, module=module)

    def clear_override(self, token: object, *, module: ModuleKey | None = None) -> None:
        """Remove any override registered for a provider."""
        self._container.clear_override(token, module=module)

    def has_override(self, token: object, *, module: ModuleKey | None = None) -> bool:
        """Check if an override is registered for a provider."""
        return self._container.has_override(token, module=module)

    def get_override(self, token: object, *, module: ModuleKey | None = None) -> object | None:
        """Retrieve the replacement object for an overridden provider."""
        return self._container.get_override(token, module=module)

    @property
    def module_graph(self) -> object:
        """Accessor for the application module graph (available during lifespan)."""
        return self.container.module_graph

    @property
    def root_module(self) -> type[object]:
        """Accessor for the root module class."""
        from ..core.module.graph import ModuleGraph
        return cast(ModuleGraph, self.module_graph).root_module

    @property
    def module_instances(self) -> Mapping[ModuleKey, object]:
        """Accessor for the instantiated modules (available during lifespan)."""
        return cast(
            Mapping[ModuleKey, object],
            getattr(self.starlette_app.state, "bustan_module_instances", {}),
        )

    @property
    def controllers(self) -> Mapping[type[object], ModuleKey]:
        """Accessor for the registered controller types to module keys."""
        return self.container.registry.controller_modules

    @property
    def routes(self) -> Mapping[str, list[object]]:
        """Accessor for the registered Starlette routes (by path)."""
        res: dict[str, list[object]] = {}
        for route in self.starlette_app.routes:
            path = getattr(route, "path", "")
            if path:
                res.setdefault(path, []).append(route)
        return res

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        """Forward ASGI calls directly to Starlette."""
        await self.starlette_app(scope, receive, send)
