"""The seam between the framework and whatever transport carries its requests.

The framework compiles routes, resolves providers and executes handlers; a transport
adapter does none of that. It translates one request into :class:`HttpRequest` and one
result back into whatever its transport writes, registers the routes it was handed,
enforces whatever policy has to sit in front of them, and starts and stops a server.
Everything named here is either a neutral value type or a method whose arguments and
return values are neutral, so an adapter can be written against this module without
importing anything else from ``bustan`` and without the framework knowing which
transport it got.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from .cors import CorsOptions
from .requests import HttpRequest
from .responses import HttpFileResponse, HttpResponse, HttpStreamResponse

# Any response the framework produces for a transport to write.
HttpResponseValue = HttpResponse | HttpStreamResponse | HttpFileResponse

# The framework's entry point for one route: given the neutral request, it returns
# either an HttpResponseValue or a response object the transport itself produced,
# which an adapter writes unchanged.
RouteHandler = Callable[[HttpRequest], Awaitable[object]]


@dataclass(frozen=True, slots=True)
class AdapterCapabilities:
    """What one transport adapter can and cannot do.

    The framework checks a route's requirements against these before compiling it, so
    an adapter that cannot serve a route says so at startup rather than at the first
    request that needs the missing capability.
    """

    supports_host_routing: bool = False
    supports_raw_body: bool = False
    supports_streaming_responses: bool = True
    supports_websocket_upgrade: bool = False


@dataclass(frozen=True, slots=True)
class AdapterRoute:
    """One route for an adapter to register, described without naming a transport.

    An adapter registers ``handler`` at ``path`` for every method in ``methods``, and
    for each request calls ``from_native_request``, awaits ``handler``, then calls
    ``to_native_response`` on the result. Every route carries a handler, and there is
    no way to hand an adapter a route already built in its own transport's terms, so
    an adapter never has to recognise an opaque object as one of its own. A route that
    reaches an adapter without a handler is a fault in the framework, and the adapter
    refuses it by name rather than registering something that cannot serve a request.

    ``requires_raw_body``, ``requires_streaming`` and ``hosts`` restate what the route
    needs from the transport, so the capability check reads the plan rather than
    reaching back into the compiled contracts.

    ``attributes`` are names and values the adapter sets on whatever it registers. The
    framework uses them to leave the compiled contract beside the route, so that
    tooling reading a running server's routes back finds what produced each one; an
    adapter that cannot carry them sets none and loses only that introspection.
    """

    path: str
    methods: tuple[str, ...]
    name: str | None = None
    handler: RouteHandler | None = None
    hosts: tuple[str, ...] = ()
    requires_raw_body: bool = False
    requires_streaming: bool = False
    attributes: tuple[tuple[str, object], ...] = ()


class AbstractHttpAdapter(ABC):
    """Base class every transport adapter implements.

    Subclasses set ``name`` to the transport they bind and ``capabilities`` to what
    that transport can serve. Nothing here is handed the dependency injection
    container, a compiled execution plan or a middleware registry: those belong to the
    framework, and an adapter that received them would have to understand them.

    ``native_request_type`` is the request type this transport builds, which is what
    ``HttpRequest.native_request`` returns for a request this adapter wrapped. It is the
    counterpart of :meth:`from_native_request`: that names the type an adapter converts,
    this names the type it produces. A handler may write a transport's request type on a
    parameter instead of the neutral one, and every transport's request object has the
    same shape, so shape alone cannot say which transport such an annotation named. This
    declaration can, and it is what lets the framework refuse that parameter before a
    server starts rather than hand it another transport's object. An adapter that leaves
    it unset produces no request type of its own, and every parameter naming one is
    refused under it.
    """

    name: str
    capabilities: AdapterCapabilities
    native_request_type: type | None = None

    @abstractmethod
    def from_native_request(self, native_request: object) -> HttpRequest:
        """Wrap one request from this transport in the neutral request contract."""

    @abstractmethod
    def to_native_response(self, response: object) -> object:
        """Convert a framework response into what this transport writes.

        The argument is an :data:`HttpResponseValue`, or a response object this
        transport itself produced because a handler returned one, which is returned
        unchanged.
        """

    @abstractmethod
    def register_routes(self, routes: Sequence[AdapterRoute]) -> None:
        """Register compiled routes with the underlying server, in the order given."""

    @abstractmethod
    async def start(
        self, port: int, host: str = "127.0.0.1", reload: bool = False, **options: object
    ) -> None:
        """Serve requests until the server stops, binding ``host`` and ``port``."""

    @abstractmethod
    async def stop(self) -> None:
        """Shut the server down and release what it holds. Doing so twice is safe."""

    @abstractmethod
    def create_test_client(self) -> object:
        """Return a client that drives this adapter in process, without a socket.

        The client is the transport's own, because that is the client its users
        already know how to drive; a conformance suite asks each adapter for one
        rather than assuming any single library.
        """

    @abstractmethod
    def get_instance(self) -> object:
        """Return the underlying server object this adapter drives."""

    @abstractmethod
    def add_middleware(self, middleware_class: type, **options: object) -> None:
        """Wrap the whole server in one of the transport's own middleware classes."""

    def enable_cors(self, options: CorsOptions) -> None:
        """Enforce one cross-origin policy on every request this transport carries.

        A preflight request is answered by the transport and never reaches a route, so
        this is the transport's work rather than the framework's, and each adapter
        implements it against whatever its own middleware looks like.

        The implementation here refuses, by name, and it is what an adapter that says
        nothing inherits. Silence has to mean refusal: an operator who calls this and is
        answered by nothing at all believes a policy is being enforced, and serves every
        origin while believing it. An adapter whose transport can enforce a policy
        overrides this and does.
        """

        raise NotImplementedError(
            f"{type(self).__name__} does not implement the CORS capability, so this "
            "adapter cannot enforce a cross-origin policy. Serve the application through "
            "an adapter that implements it, or enforce the policy in front of the process."
        )

    async def listen(
        self, port: int, host: str = "127.0.0.1", reload: bool = False, **options: object
    ) -> None:
        """Serve requests, under the name the application wrapper calls.

        This exists so that one verb reaches the server from the application object and
        another from the port itself; both run :meth:`start`, which is the one an
        adapter implements.
        """

        await self.start(port, host=host, reload=reload, **options)

    async def __call__(self, *connection: object) -> None:
        """Serve one connection the transport handed straight to this adapter.

        A transport calls a server with whatever arguments that transport defines, so
        the framework only forwards them. An adapter whose transport has no such entry
        point leaves this alone and is never called this way.
        """

        raise NotImplementedError(
            f"{type(self).__name__} cannot serve a connection directly; "
            "start a server with start() instead"
        )


__all__ = (
    "AbstractHttpAdapter",
    "AdapterCapabilities",
    "AdapterRoute",
    "HttpResponseValue",
    "RouteHandler",
)
