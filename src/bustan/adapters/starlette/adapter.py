"""The Starlette transport adapter."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, cast

from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Match

from ...contracts import AbstractHttpAdapter, AdapterCapabilities, HttpRequest
from ...contracts.cors import allowed_origins
from ...runtime.execution import method_not_allowed_response, not_found_response
from .requests import from_starlette_request
from .responses import to_starlette_response
from .routes import build_starlette_routes
from .shutdown import DrainGate, DrainingApp

if TYPE_CHECKING:
    from collections.abc import Sequence

    from starlette.types import ExceptionHandler

    from ...contracts import AdapterRoute
    from ...contracts.cors import CorsOptions
    from .server import GracefulServer, ShutdownSequence

_TEST_CLIENT_REQUIREMENT = (
    "A Starlette test client requires the optional 'httpx' dependency. "
    "Install httpx to drive the application in process."
)

# How long the requests already in flight are given to finish once a shutdown has
# begun. Long enough that an ordinary request finishes, short enough that an orchestrator
# replacing this process does not give up on it and kill it instead.
DEFAULT_DRAIN_TIMEOUT_SECONDS = 10.0

# What the server itself is given after the drain window has closed. Whatever is still
# running by then is already past its deadline, so the server is left only long enough to
# write out the responses it can before it cancels the rest. Handing it the drain window
# a second time would spend a timeout the caller set once, twice.
_SERVER_GRACE_SECONDS = 1


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
    # What this transport builds for every request it carries, and so what a handler
    # naming this transport's request type is handed.
    native_request_type = Request

    def __init__(
        self,
        starlette_app: Starlette | None = None,
        *,
        debug: bool = False,
        lifespan: Any | None = None,
        drain_timeout: float = DEFAULT_DRAIN_TIMEOUT_SECONDS,
    ) -> None:
        """Wrap an existing Starlette application, or build one from ``debug`` and ``lifespan``.

        ``drain_timeout`` is how many seconds the requests already in flight are given
        to finish when the server is asked to stop. The application wrapper overrides it
        for one run when its own caller names a different window.

        Whichever application is used, the router's own refusals are answered through the
        framework's error model and its own slash redirect is turned off. An application
        handed in already carrying handlers for those two statuses, or a router left to
        redirect for itself, is overruled, because the error model and the shape of a
        redirect are the framework's promise to the caller rather than the transport's.
        """

        self._app = starlette_app or Starlette(debug=debug, lifespan=lifespan)
        # Starlette decides the slash redirect in the router, ahead of the endpoint whose
        # refusal the handlers below answer, so the table cannot reach it and it is turned
        # off instead. What the router would have sent is an absolute location built from
        # the caller's own Host header, for a path with every trailing slash stripped
        # rather than one; with this off, both are decided in `_refuse_unmatched_route`.
        self._app.router.redirect_slashes = False
        for status_code, refuse in _ROUTER_REFUSALS:
            self._app.add_exception_handler(status_code, refuse)
        self._server: GracefulServer | None = None
        self._stopped: asyncio.Event | None = None
        self._gate = DrainGate()
        self._drain_timeout = drain_timeout
        self._shut_down_application: ShutdownSequence | None = None

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

    def enable_cors(self, options: CorsOptions) -> None:
        """Enforce *options* through Starlette's own CORS middleware."""

        self.add_middleware(
            CORSMiddleware,
            allow_origins=allowed_origins(options),
            allow_methods=options.methods,
            allow_headers=options.allowed_headers,
            expose_headers=options.exposed_headers,
            allow_credentials=options.credentials,
            max_age=options.max_age,
        )

    @property
    def draining(self) -> bool:
        """Whether the running server has stopped accepting new requests.

        A process that answers this with true is on its way down and should be taken
        out of rotation; it is what a readiness check on this adapter reports.
        """

        return self._gate.draining

    @property
    def in_flight(self) -> int:
        """How many requests the running server is serving at this moment."""

        return self._gate.in_flight

    def prepare_graceful_shutdown(
        self, shut_down: ShutdownSequence, drain_timeout: float | None = None
    ) -> None:
        """Hand the adapter the application teardown to run once the server has drained.

        The drain and the teardown are one sequence rather than two, because a teardown
        that ran while requests were still being served would destroy what those
        requests are being served from. Passing ``drain_timeout`` sets the window for
        the runs that follow; leaving it out keeps the one this adapter was built with.
        """

        self._shut_down_application = shut_down
        if drain_timeout is not None:
            self._drain_timeout = drain_timeout

    async def start(
        self, port: int, host: str = "127.0.0.1", reload: bool = False, **options: object
    ) -> None:
        """Serve the application with Uvicorn until the server stops.

        A signal that arrives while this is serving stops the server the graceful way:
        new requests are refused, the ones in flight are given the drain window, the
        application's shutdown hooks run with the signal's name, and only then is the
        listening socket released.

        ``reload`` is refused rather than ignored: reloading means owning the process,
        watching the source tree and restarting it, which belongs to a development server
        rather than to an adapter, and claiming it while doing nothing would be worse.
        Uvicorn reloads only from its own supervisor, which restarts the worker and so
        reaches an application only by importing it by name; this serves the live
        application object it was handed, which a restart has no way to rebuild.
        """

        if reload:
            raise NotImplementedError(
                "The Starlette adapter has no reloader; uvicorn reloads only from its "
                "own supervisor, so run uvicorn with the application named as an "
                "import string"
            )

        import uvicorn

        from .server import GracefulServer

        settings = dict(options)
        settings.setdefault("timeout_graceful_shutdown", _SERVER_GRACE_SECONDS)
        # A gate belongs to one run: a server started again after one was drained must
        # not inherit a gate that is already closed against every caller.
        self._gate = DrainGate()
        config = uvicorn.Config(
            DrainingApp(self._app, self._gate),
            host=host,
            port=port,
            **cast(Any, settings),
        )
        server = GracefulServer(config, self._gate, self._drain_and_tear_down)
        self._server = server
        self._stopped = asyncio.Event()
        try:
            await server.serve()
        finally:
            self._server = None
            stopped, self._stopped = self._stopped, None
            if stopped is not None:
                stopped.set()

    async def stop(self) -> None:
        """Stop a running server and wait for it to release its socket.

        Returning only once the server has stopped is what lets a caller act on the
        stop: bind the port again, or start the application a second time. Stopping when
        no server runs does nothing, and stopping one twice is harmless.
        """

        server = self._server
        if server is None:
            return
        # Uvicorn's own signal handling sets this flag, and its serve loop exits on the
        # next pass, which is what makes a second call harmless.
        server.should_exit = True
        stopped = self._stopped
        if stopped is not None:
            await stopped.wait()

    async def _drain_and_tear_down(self, signal_name: str | None) -> None:
        """Refuse new requests, wait for the ones in flight, then tear the application down.

        The wait is bounded. A request that outlasts the window is left to the server,
        which cancels it, because a shutdown that waited on it indefinitely would be a
        shutdown one slow caller could refuse to allow.
        """

        self._gate.begin_drain()
        await self._gate.wait_until_idle(self._drain_timeout)
        if self._shut_down_application is not None:
            await self._shut_down_application(signal_name)

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


async def _refuse_unmatched_route(request: Request, _exc: Exception) -> Response:
    """Answer a path this router found no route for.

    A path is tried once more with its trailing slash written the other way round, and a
    caller who spelled it the way no route was registered is sent to the way one was. Only
    then is it a path nothing here answers, and answered with the framework's document.
    """

    redirect = _slash_redirect(request)
    if redirect is not None:
        return redirect
    return to_starlette_response(not_found_response(_requested_path(request)))


async def _refuse_wrong_method(request: Request, exc: Exception) -> Response:
    """Answer a method this router will not serve with the framework's own document."""

    return to_starlette_response(
        method_not_allowed_response(_requested_path(request), _allowed_methods(exc))
    )


def _slash_redirect(request: Request) -> Response | None:
    """Return the redirect for a path only a trailing slash separates from a route.

    ``None`` where no route answers the other spelling, which leaves the caller with the
    not-found document. The redirect names no media type, because it carries no body and
    a response with no content should not say what content it has.
    """

    alternate = _alternate_path(_requested_path(request))
    if not alternate or not _any_route_answers(request, alternate):
        return None
    return Response(status_code=307, headers={"location": _redirect_location(request)})


def _alternate_path(path: str) -> str:
    """Return *path* spelled the other way round: its trailing slash added or removed.

    One slash, not every slash: ``/shop/orders//`` is a path of its own rather than the
    slashed spelling of a route, and a transport that rewrote it would answer a request
    the caller did not send. It is also the spelling the redirect sends the caller to, so
    the retry and the location are one expression; a location built by a second one would
    eventually send a caller to a path the router had not agreed to answer.

    Written here rather than imported from the raw ASGI transport. The two transports are
    independent by design, and a rule this short costs less stated twice than the
    dependency of one adapter on the other would.
    """

    return path.removesuffix("/") if path.endswith("/") else f"{path}/"


def _any_route_answers(request: Request, path: str) -> bool:
    """Whether any route on this application answers *path*, by whatever method.

    A route that answers the path but not the method still counts, because a caller sent
    to it reads the framework's 405 there rather than a 404 here, which is the more
    accurate of the two answers.
    """

    scope = {**request.scope, "path": path}
    return any(route.matches(scope)[0] is not Match.NONE for route in request.app.routes)


def _redirect_location(request: Request) -> str:
    """Return where a request whose path is spelled the other way round is sent.

    Relative. An absolute location can only be built from the caller's own ``Host``
    header, which names the wrong host behind any proxy that terminates TLS, and which is
    client-controlled input reflected into a redirect even where it names the right one.

    Built from the target the caller wrote rather than the path Starlette decoded from it.
    The two say the same thing, but only the first can be sent back: a path is decoded, so
    a caller who addressed ``/users/John%20Doe/`` would be redirected to a location with a
    space loose in it, and the request that came back would be a different one or none. A
    scope carrying no raw path is redirected to the path it did carry.
    """

    raw_path = cast("bytes | None", request.scope.get("raw_path"))
    target = _requested_path(request) if raw_path is None else raw_path.decode("latin-1")
    location = _alternate_path(target)
    query = cast(bytes, request.scope.get("query_string", b"")).decode("latin-1")
    return f"{location}?{query}" if query else location


def _requested_path(request: Request) -> str:
    """The path the caller asked for, read from the connection rather than rebuilt.

    Starlette builds a request's URL out of the ``Host`` header among other things, and
    a refusal is answered for whatever arrived, including a request carrying no headers
    at all. The path is on the connection either way.
    """

    return cast(str, request.scope.get("path", "/"))


def _allowed_methods(exc: Exception) -> tuple[str, ...]:
    """The methods the router would have answered, read off the refusal it raised.

    Starlette states them on the refusal as the ``Allow`` header it would have sent. The
    framework writes that header itself, from these, so what a caller reads is decided
    in one place for every transport rather than by each transport's own set ordering.
    """

    allow = (getattr(exc, "headers", None) or {}).get("Allow", "")
    return tuple(method.strip() for method in allow.split(",") if method.strip())


# The refusals Starlette's own router decides, by status, and what answers each. The
# router turns a request away before any endpoint runs, so nothing the framework put on
# a route stands between these and the caller; left to the transport they would be the
# only errors an application serves outside its own error model, and they are the two it
# serves most often.
_ROUTER_REFUSALS: tuple[tuple[int, ExceptionHandler], ...] = (
    (404, _refuse_unmatched_route),
    (405, _refuse_wrong_method),
)


__all__ = ("StarletteAdapter",)
