"""The ASGI application this adapter drives: a router, a lifespan and a middleware stack.

Nothing here is a server. This object is what a server - or a test client - calls with
one connection at a time, which is the whole of what ASGI defines an application to be.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING, cast

from ...contracts import RequestState
from .requests import DEFAULT_MAX_BODY_BYTES, AsgiHttpRequest
from .responses import AsgiResponseValue, plain_text, to_asgi_response
from .routing import AsgiRouter, Matched, MethodMismatch, Redirect, build_asgi_routes

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ...contracts import AdapterRoute
    from .routing import AsgiRoute
    from .types import AsgiApp, Message, Receive, Scope, Send

# Builds the context manager whose entry is application startup and whose exit is
# application shutdown, given the application it is being run for.
Lifespan = Callable[["AsgiApplication"], AbstractAsyncContextManager[None]]


class AsgiApplication:
    """One application: the routes it serves, the middleware around them, its lifespan.

    ``state`` is the namespace the framework attaches what it wants to reach from a
    request to, which is how a handler can ask for the application it is running inside.
    """

    def __init__(
        self,
        *,
        lifespan: Lifespan | None = None,
        max_body_bytes: int | None = DEFAULT_MAX_BODY_BYTES,
    ) -> None:
        self.router = AsgiRouter()
        self.state = RequestState()
        self._lifespan = lifespan
        self._max_body_bytes = max_body_bytes
        self._middleware: list[tuple[type, dict[str, object]]] = []
        self._stack: AsgiApp | None = None

    @property
    def routes(self) -> list[AsgiRoute]:
        """The routes registered on this application, in registration order."""

        return self.router.routes

    def register(self, routes: Sequence[AdapterRoute]) -> None:
        """Register a compiled route plan, in the order it was given."""

        self.router.add(build_asgi_routes(routes))

    def add_middleware(self, middleware_class: type, **options: object) -> None:
        """Wrap the application in one ASGI middleware class.

        The most recently added wraps outermost and so sees a request first, which is the
        order an ASGI server composes a stack in.
        """

        self._middleware.append((middleware_class, options))
        self._stack = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Serve one connection.

        A lifespan connection is answered directly rather than through the middleware
        stack: middleware wraps the serving of requests, and an application whose startup
        depended on which middleware was installed would be a surprise.
        """

        scope["app"] = self
        scope.setdefault("state", {})
        connection_type = scope.get("type")
        if connection_type == "lifespan":
            await self._run_lifespan(receive, send)
            return
        if connection_type != "http":
            raise NotImplementedError(
                f"The ASGI adapter serves http and lifespan connections, not {connection_type!r}"
            )
        await self._build_stack()(scope, receive, send)

    def _build_stack(self) -> AsgiApp:
        if self._stack is None:
            stack: AsgiApp = self._serve_http
            for middleware_class, options in self._middleware:
                stack = cast("AsgiApp", middleware_class(stack, **options))
            self._stack = stack
        return self._stack

    async def _serve_http(self, scope: Scope, receive: Receive, send: Send) -> None:
        request = AsgiHttpRequest(scope, receive, max_body_bytes=self._max_body_bytes)
        response = await self._resolve(request)
        if request.method == "HEAD":
            # A HEAD answer carries the headers its GET would have carried, the content
            # length included, and none of the body.
            await response(_without_body(send))
            return
        await response(send)

    async def _resolve(self, request: AsgiHttpRequest) -> AsgiResponseValue:
        resolution = self.router.resolve(request.path, request.method)
        if isinstance(resolution, Matched):
            request.set_path_params(resolution.path_params)
            return to_asgi_response(await resolution.route.handler(request))
        if isinstance(resolution, MethodMismatch):
            return plain_text(
                "Method Not Allowed", status_code=405, allow=", ".join(resolution.allowed)
            )
        if isinstance(resolution, Redirect):
            query = cast(bytes, request.scope.get("query_string", b"")).decode("latin-1")
            location = f"{resolution.path}?{query}" if query else resolution.path
            return plain_text("", status_code=307, location=location)
        return plain_text("Not Found", status_code=404)

    async def _run_lifespan(self, receive: Receive, send: Send) -> None:
        """Run the ASGI lifespan protocol until the server says shutdown."""

        context = None if self._lifespan is None else self._lifespan(self)
        while True:
            message: Message = await receive()
            if message.get("type") == "lifespan.startup":
                await self._enter_lifespan(context, send)
            elif message.get("type") == "lifespan.shutdown":
                await self._exit_lifespan(context, send)
                return

    async def _enter_lifespan(
        self, context: AbstractAsyncContextManager[None] | None, send: Send
    ) -> None:
        """Start the application, reporting a failure the way the protocol defines.

        A startup that raises is reported as ``lifespan.startup.failed`` rather than
        propagating, because a server reads that message to decide not to bind a port and
        an exception escaping here would leave it with nothing to read.
        """

        try:
            if context is not None:
                await context.__aenter__()
        except Exception as error:
            await send({"type": "lifespan.startup.failed", "message": str(error)})
            return
        await send({"type": "lifespan.startup.complete"})

    async def _exit_lifespan(
        self, context: AbstractAsyncContextManager[None] | None, send: Send
    ) -> None:
        """Stop the application, reporting a failure the way the protocol defines."""

        try:
            if context is not None:
                await context.__aexit__(None, None, None)
        except Exception as error:
            await send({"type": "lifespan.shutdown.failed", "message": str(error)})
            return
        await send({"type": "lifespan.shutdown.complete"})

    def __repr__(self) -> str:
        return f"{type(self).__name__}(routes={len(self.routes)})"


def _without_body(send: Send) -> Send:
    """Return *send* with the bytes of every body message removed."""

    async def send_headers_only(message: Message) -> None:
        if message.get("type") == "http.response.body":
            message = {**message, "body": b""}
        await send(message)

    return send_headers_only


__all__ = (
    "AsgiApplication",
    "Lifespan",
)
