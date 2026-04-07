"""Public application wrapper and context for the Bustan framework."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Callable, cast

if TYPE_CHECKING:
    from ..core.ioc.container import Container
    from ..platform.http.adapter import AbstractHttpAdapter


class ApplicationContext:
    """A standalone application context for dependency injection.

    This provides a clean interface for resolving services from the Bustan
    IoC container, without an associated HTTP server instance.
    """

    def __init__(self, container: Container) -> None:
        self._container = container

    @property
    def _root_module(self) -> type[object]:
        """Internal accessor for the root module class."""
        from ..core.module.graph import ModuleGraph

        return cast(ModuleGraph, self._container.module_graph).root_module

    def get(self, token: object) -> Any:
        """Resolve a provider from the root module context.

        This is a non-request-scoped resolution. For request-scoped
        providers, use the container directly within a request context.
        """
        return self._container.resolve(token, module=self._root_module)

    def resolve(self, token: object) -> Any:
        """Alias for app.get()."""
        return self.get(token)

    async def close(self) -> None:
        """Trigger the application shutdown sequence.

        Mainly used for graceful teardown in tests.
        """
        # Close the container (not yet implemented in Container but good for future)
        pass


class Application(ApplicationContext):
    """A high-level application wrapper for HTTP services.

    This class extends the ApplicationContext with an HTTP server instance managed
    via an AbstractHttpAdapter.
    """

    def __init__(self, adapter: AbstractHttpAdapter, container: Container) -> None:
        super().__init__(container)
        self._adapter = adapter

    def get_http_adapter(self) -> AbstractHttpAdapter:
        """Accessor for the underlying HTTP framework adapter."""
        return self._adapter

    def get_http_server(self) -> Any:
        """Accessor for the underlying framework instance (e.g., Starlette App)."""
        return self._adapter.get_instance()

    async def listen(
        self, port: int, host: str = "127.0.0.1", reload: bool = False, **kwargs: Any
    ) -> None:
        """Start the ASGI server asynchronously via the adapter."""
        await self._adapter.listen(port, host=host, reload=reload, **kwargs)

    @property
    def routes(self) -> Mapping[str, list[object]]:
        """Accessor for the registered routes (by path)."""
        res: dict[str, list[object]] = {}
        instance = self.get_http_server()
        if hasattr(instance, "routes"):
            for route in instance.routes:
                path = getattr(route, "path", "")
                if path:
                    res.setdefault(path, []).append(route)
        return res

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        """Forward ASGI calls directly to the underlying HTTP adapter."""
        await self._adapter(scope, receive, send)
