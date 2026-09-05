"""The Starlette transport adapter."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from starlette.applications import Starlette
from starlette.responses import Response

from ...contracts import AbstractHttpAdapter, AdapterCapabilities, HttpRequest
from .requests import from_starlette_request
from .responses import to_starlette_response
from .routes import build_starlette_routes

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ...contracts import AdapterRoute

_TEST_CLIENT_REQUIREMENT = (
    "A Starlette test client requires the optional 'httpx' dependency. "
    "Install httpx to drive the application in process."
)


class StarletteAdapter(AbstractHttpAdapter):
    """Serve a Bustan application over Starlette, with Uvicorn as the server.

    The adapter owns one Starlette application and nothing else: it converts requests
    and responses, registers the routes the framework compiled, and runs the server.
    Route compilation, provider resolution and handler execution stay in the
    framework, so this class never sees the container.
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
        lifespan: Any | None = None,
    ) -> None:
        """Wrap an existing Starlette application, or build one from ``debug`` and ``lifespan``."""

        self._app = starlette_app or Starlette(debug=debug, lifespan=lifespan)
        self._server: object | None = None

    def get_instance(self) -> Starlette:
        """Return the Starlette application this adapter drives."""

        return self._app

    def from_native_request(self, native_request: object) -> HttpRequest:
        """Return the neutral request contract for one Starlette request."""

        return from_starlette_request(native_request)

    def to_native_response(self, response: object) -> Response:
        """Return the Starlette response that writes a framework response."""

        return to_starlette_response(response)

    def register_routes(self, routes: Sequence[AdapterRoute]) -> None:
        """Append the compiled routes to the Starlette application, in order."""

        self._app.routes.extend(build_starlette_routes(routes))

    def add_middleware(self, middleware_class: type, **options: object) -> None:
        """Wrap the Starlette application in one of Starlette's middleware classes."""

        self._app.add_middleware(cast(Any, middleware_class), **options)

    async def start(
        self, port: int, host: str = "127.0.0.1", reload: bool = False, **options: object
    ) -> None:
        """Serve the application with Uvicorn until the server stops."""

        import uvicorn

        config = uvicorn.Config(
            self._app, host=host, port=port, reload=reload, **cast(Any, options)
        )
        server = uvicorn.Server(config)
        self._server = server
        try:
            await server.serve()
        finally:
            self._server = None

    async def stop(self) -> None:
        """Ask a running server to shut down; doing so when none runs does nothing."""

        server = self._server
        if server is None:
            return
        # Uvicorn's own signal handling sets this flag, and its serve loop exits on the
        # next pass, which is what makes a second call harmless.
        setattr(server, "should_exit", True)  # noqa: B010

    def create_test_client(self) -> object:
        """Return Starlette's test client, bound to this application."""

        try:
            from starlette.testclient import TestClient
        except ModuleNotFoundError as exc:
            if exc.name != "httpx":
                raise
            raise ImportError(_TEST_CLIENT_REQUIREMENT) from exc
        except RuntimeError as exc:
            if "httpx" not in str(exc):
                raise
            raise ImportError(_TEST_CLIENT_REQUIREMENT) from exc

        return TestClient(self._app)

    async def __call__(self, *connection: object) -> None:
        """Serve one ASGI connection through the Starlette application."""

        scope, receive, send = connection
        await self._app(cast(Any, scope), cast(Any, receive), cast(Any, send))


__all__ = ("StarletteAdapter",)
