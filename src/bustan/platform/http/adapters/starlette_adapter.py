"""Starlette adapter implementation for the Bustan framework."""

from __future__ import annotations

from typing import Any, Callable, cast

import uvicorn
from starlette.applications import Starlette
from starlette.routing import BaseRoute

from ..adapter import AbstractHttpAdapter, AdapterCapabilities, CompiledAdapterRoute


class StarletteAdapter(AbstractHttpAdapter):
    """Bustan adapter for the Starlette web framework.

    This adapter manages a Starlette application instance and handles
    asynchronous server initialization via Uvicorn.
    """

    name = "starlette"
    capabilities = AdapterCapabilities(
        supports_host_routing=False,
        supports_raw_body=True,
        supports_streaming_responses=True,
        supports_websocket_upgrade=False,
    )

    def __init__(
        self, 
        starlette_app: Starlette | None = None,
        *,
        debug: bool = False,
        lifespan: Any | None = None
    ) -> None:
        """Initialize the Starlette adapter.

        If a Starlette app is not provided, a new one will be created with
         the specified debug and lifespan configuration.
        """
        self._app = starlette_app or Starlette(debug=debug, lifespan=lifespan)

    def get_instance(self) -> Starlette:
        """Return the underlying Starlette instance."""
        return self._app

    def register_routes(self, routes: list[CompiledAdapterRoute]) -> None:
        """Register routes into the Starlette application."""
        registrations: list[BaseRoute] = [
            cast(BaseRoute, route.registration) for route in routes
        ]
        self._app.routes.extend(registrations)

    def add_middleware(self, middleware_class: type, **options: Any) -> None:
        """Register middleware on the underlying Starlette application."""
        self._app.add_middleware(middleware_class, **options)

    async def listen(
        self, 
        port: int, 
        host: str = "127.0.0.1", 
        reload: bool = False, 
        **kwargs: Any
    ) -> None:
        """Start the ASGI server asynchronously using Uvicorn."""
        config = uvicorn.Config(
            self._app, 
            host=host, 
            port=port, 
            reload=reload, 
            **kwargs
        )
        server = uvicorn.Server(config)
        await server.serve()

    async def close(self) -> None:
        """Shutdown the Starlette application."""
        pass

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        """Forward ASGI calls directly to the Starlette instance."""
        await self._app(scope, receive, send)
