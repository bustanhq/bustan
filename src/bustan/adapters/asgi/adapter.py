"""The raw ASGI transport adapter."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from ...contracts import AbstractHttpAdapter, AdapterCapabilities, HttpRequest
from .application import AsgiApplication
from .requests import DEFAULT_MAX_BODY_BYTES, from_asgi_request
from .responses import AsgiResponseValue, to_asgi_response
from .server import AsgiServer
from .testclient import AsgiTestClient

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ...contracts import AdapterRoute
    from .application import Lifespan
    from .types import Receive, Scope, Send


class AsgiAdapter(AbstractHttpAdapter):
    """Serve a Bustan application over raw ASGI, with no web framework underneath.

    Every other adapter binds a server library, and a library can quietly become the only
    way the framework works. This one binds nothing: it implements the adapter port
    against the ASGI specification and the standard library alone, so anything the
    framework comes to need from a transport that ASGI does not define shows up here as a
    failure rather than as a dependency nobody noticed taking on.

    That makes it a permanent commitment rather than a demonstration. A change that makes
    this adapter hard to keep working has found a coupling, and finding it is the point.
    """

    name = "asgi"
    capabilities = AdapterCapabilities(
        supports_host_routing=False,
        supports_raw_body=True,
        supports_streaming_responses=True,
        supports_websocket_upgrade=False,
    )

    def __init__(
        self,
        application: AsgiApplication | None = None,
        *,
        lifespan: Lifespan | None = None,
        max_body_bytes: int | None = DEFAULT_MAX_BODY_BYTES,
    ) -> None:
        """Wrap an existing ASGI application, or build one that runs ``lifespan``.

        ``max_body_bytes`` bounds what one request may send, because a body is read into
        memory before it is parsed; ``None`` removes the bound for a deployment that has
        decided it wants that.
        """

        self._app = application or AsgiApplication(lifespan=lifespan, max_body_bytes=max_body_bytes)
        self._max_body_bytes = max_body_bytes
        self._server: AsgiServer | None = None

    def get_instance(self) -> AsgiApplication:
        """Return the ASGI application this adapter drives."""

        return self._app

    def from_native_request(self, native_request: object) -> HttpRequest:
        """Return the neutral request contract for one request this transport carries."""

        return from_asgi_request(native_request)

    def to_native_response(self, response: object) -> AsgiResponseValue:
        """Return the ASGI response that writes a framework response."""

        return to_asgi_response(response)

    def register_routes(self, routes: Sequence[AdapterRoute]) -> None:
        """Register the compiled routes on the application, in the order given."""

        self._app.register(routes)

    def add_middleware(self, middleware_class: type, **options: object) -> None:
        """Wrap the application in one ASGI middleware class."""

        self._app.add_middleware(middleware_class, **options)

    async def start(
        self, port: int, host: str = "127.0.0.1", reload: bool = False, **options: object
    ) -> None:
        """Serve the application over HTTP until :meth:`stop` is called.

        ``reload`` is refused rather than ignored: reloading means owning the process,
        watching the source tree and restarting it, which belongs to a development server
        rather than to an adapter, and claiming it while doing nothing would be worse.
        """

        if reload:
            raise NotImplementedError(
                "The ASGI adapter has no reloader; run it under a server that provides one"
            )
        server = AsgiServer(
            self._app, host=host, port=port, max_body_bytes=self._max_body_bytes, **options
        )
        self._server = server
        try:
            await server.serve()
        finally:
            self._server = None

    async def stop(self) -> None:
        """Ask a running server to shut down; doing so when none runs does nothing."""

        server = self._server
        if server is not None:
            await server.stop()

    def create_test_client(self) -> AsgiTestClient:
        """Return a client that drives this application in process, without a socket."""

        return AsgiTestClient(self._app)

    async def __call__(self, *connection: object) -> None:
        """Serve one ASGI connection through the application."""

        scope, receive, send = connection
        await self._app(cast("Scope", scope), cast("Receive", receive), cast("Send", send))


__all__ = ("AsgiAdapter",)
