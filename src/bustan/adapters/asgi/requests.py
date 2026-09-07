"""The neutral request contract, backed by one raw ASGI connection."""

from __future__ import annotations

import json
from http.cookies import SimpleCookie
from typing import TYPE_CHECKING, NoReturn, cast

from ...contracts import (
    Headers,
    HttpClientInfo,
    HttpFormData,
    HttpRequest,
    HttpRequestState,
    QueryParams,
    RequestSlots,
    RequestState,
    Url,
    request_slots,
)
from .forms import parse_form_body

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .types import Message, Receive, Scope

# How many body bytes this transport will read for a request that has no application
# behind it to say. A body is read into memory to be parsed, so an unauthenticated
# caller could otherwise grow that buffer without limit.
#
# The number is twice the largest body the framework's own request limits accept under
# their defaults, and the doubling is the point rather than the value: this is a
# backstop and not the bound a caller is normally answered by. What answers a caller is
# the limit the application serving the request declared, which is read per request and
# is lower; this only stands where there is no application to ask, and caps a limit that
# has been raised above it. A deployment that raises the framework's limits past this
# raises this too, by building the adapter with a ``max_body_bytes`` of its own. The
# figure is written out rather than derived from the framework's, because reading it
# from there would make this package import the framework at module scope and it
# deliberately imports nothing but the request contracts.
DEFAULT_MAX_BODY_BYTES = 20 * 1024 * 1024


class ClientDisconnected(ConnectionError):
    """Raised when the client went away before its body had finished arriving."""


class AsgiHttpRequest:
    """One raw ASGI request, seen through the framework's neutral request contract.

    Every property returns a neutral value, so framework code reading a request through
    this class receives nothing that belongs to a transport. Raw ASGI has no request
    object of its own - a request *is* the scope and the receive callable - so
    ``native_request`` returns this wrapper, whose ``scope`` and ``receive`` are the two
    objects the server actually handed over.

    The body is read at most once and kept, because ASGI delivers it as a stream that
    cannot be rewound and more than one stage of a request may ask for it. It is read
    under the byte bound the application serving the request declared, and the read stops
    at the chunk that crosses that bound, so a body the application will not accept is
    never held here in full. A body already read was read under one of the bounds that
    application itself declared, so a later reader is handed it rather than having it
    judged again here; what the framework accepts for a particular parameter is the
    framework's own check, made on the bytes it is handed.
    """

    __slots__ = ("_body", "_max_body_bytes", "_path_params", "_receive", "_scope", "_state")

    def __init__(
        self,
        scope: Scope,
        receive: Receive,
        *,
        path_params: Mapping[str, str] | None = None,
        max_body_bytes: int | None = DEFAULT_MAX_BODY_BYTES,
    ) -> None:
        self._scope = scope
        self._receive = receive
        self._path_params: dict[str, str] = dict(path_params or {})
        self._max_body_bytes = max_body_bytes
        self._body: bytes | None = None
        self._state: RequestState | None = None

    @property
    def native_request(self) -> AsgiHttpRequest:
        """This request; raw ASGI has no request object of its own to hand back."""

        return self

    @property
    def scope(self) -> Scope:
        """The connection scope the server built for this request."""

        return self._scope

    @property
    def receive(self) -> Receive:
        """The callable the body arrives on."""

        return self._receive

    @property
    def method(self) -> str:
        """The HTTP method, upper case."""

        return cast(str, self._scope.get("method", "GET")).upper()

    @property
    def path(self) -> str:
        """The request path, without the query string."""

        return cast(str, self._scope.get("path", "/"))

    @property
    def url(self) -> Url:
        """The request URL as plain data."""

        host, port = self._authority()
        return Url(
            scheme=cast(str, self._scope.get("scheme", "http")),
            host=host,
            port=port,
            path=self.path,
            query_string=self._query_string(),
        )

    @property
    def headers(self) -> Headers:
        """The request headers, looked up without regard to case."""

        raw = cast("list[tuple[bytes, bytes]]", self._scope.get("headers", []))
        return Headers((name.decode("latin-1"), value.decode("latin-1")) for name, value in raw)

    @property
    def query_params(self) -> QueryParams:
        """The decoded query string, keeping every value of a repeated key."""

        return QueryParams.from_query_string(self._query_string())

    @property
    def path_params(self) -> Mapping[str, str]:
        """The parameters the router captured from the path."""

        return dict(self._path_params)

    @property
    def cookies(self) -> Mapping[str, str]:
        """The cookies the request carried."""

        jar: SimpleCookie = SimpleCookie()
        for header in self.headers.getlist("cookie"):
            jar.load(header)
        return {name: morsel.value for name, morsel in jar.items()}

    @property
    def state(self) -> HttpRequestState:
        """The open per-request namespace, sharing storage with the connection scope."""

        if self._state is None:
            # ASGI reserves this scope entry for per-request state, so a view over it is
            # the same storage rather than a second copy that would drift.
            self._scope.setdefault("state", {})
            self._state = RequestState(self._scope["state"])
        return self._state

    @property
    def slots(self) -> RequestSlots:
        """The framework's typed per-request slots, created on first use."""

        return request_slots(self.state)

    @property
    def client(self) -> HttpClientInfo | None:
        """Who connected, when the server reported it."""

        client = self._scope.get("client")
        if client is None:
            return None
        host, port = cast("tuple[str, int]", client)
        return HttpClientInfo(host=host, port=port)

    @property
    def app(self) -> object:
        """The application object the server attached to the connection."""

        return self._scope.get("app")

    async def body(self) -> bytes:
        """Read the whole request body, refusing one over the application's body limit.

        The refusal happens at the chunk that crosses the limit rather than after the
        last one, so a body the application will not accept is never held here in full.
        The limit is the one the application serving this request declared, read now
        rather than when the request was wrapped, because an application declares its
        limits after its routes are built.
        """

        if self._body is None:
            body_bound, _ = self._declared_bounds()
            self._body = await self._read_body(body_bound)
        return self._body

    async def json(self) -> object:
        """Read the request body under the body limit and decode it as JSON."""

        return json.loads(await self.body())

    async def form(self) -> HttpFormData:
        """Read the request body as form data, uploaded files included.

        A form is read under the application's upload bound rather than its body bound,
        because those are two figures for two different things: a route that accepts
        uploads is expected to carry more than a JSON document, and reading a form under
        the smaller of the two would refuse an upload the application was configured to
        serve.
        """

        if self._body is None:
            _, upload_bound = self._declared_bounds()
            self._body = await self._read_body(upload_bound)
        return parse_form_body(self._body, self.headers.get("content-type"))

    def set_path_params(self, path_params: Mapping[str, str]) -> None:
        """Record what a router captured from the path, before the handler is called."""

        self._path_params = dict(path_params)

    async def _read_body(self, declared: int | None) -> bytes:
        """Read the body, stopping at the chunk that carries it past a bound.

        Two bounds, checked in this order because they belong to different owners and a
        caller is owed the answer of whichever refused. *declared* is the limit the
        application serving this request set and is normally the lower of the two, so it
        is what a caller is normally told; this transport's own ceiling stands behind it
        for a request with no application to declare one, and for a declared limit raised
        past the ceiling without the ceiling being raised too.
        """

        chunks: list[bytes] = []
        received = 0
        more = True
        while more:
            message: Message = await self._receive()
            if message.get("type") == "http.disconnect":
                raise ClientDisconnected("The client disconnected before its body arrived")
            chunk = cast(bytes, message.get("body", b""))
            received += len(chunk)
            # Whatever the client is still sending is left unread from here. Reading to
            # the end to be polite about it would spend exactly the memory the bound
            # exists to refuse, and the bytes already counted are not reported for the
            # same reason: totalling them means reading them.
            if declared is not None and received > declared:
                self._refuse(f"The request body exceeds the {declared} byte limit")
            ceiling = self._max_body_bytes
            if ceiling is not None and received > ceiling:
                self._refuse(f"The request body carries more than the {ceiling} byte limit")
            chunks.append(chunk)
            more = bool(message.get("more_body", False))
        return b"".join(chunks)

    def _refuse(self, message: str) -> NoReturn:
        """Refuse a body over a bound, in the terms the framework refuses one in.

        The framework's own error rather than one of this package's, so that the filter
        which renders a limit refusal recognises it: a caller who sent too much is told
        so, instead of being told the server broke and having the refusal logged as a
        fault.

        The import is made here rather than at module scope because this package imports
        nothing but the request contracts, and a body is only ever refused while the
        framework that owns this class is already running.
        """

        from ...runtime.params import RequestBodyTooLargeError

        raise RequestBodyTooLargeError(message)

    def _declared_bounds(self) -> tuple[int | None, int | None]:
        """Return the byte bounds the application declared for a body and for a form.

        They are two figures for two different things: a route that accepts uploads is
        expected to carry more than a JSON document, so reading a form under the body
        bound would refuse an upload the application was configured to serve.

        The application is asked now rather than when the request was wrapped, because an
        application declares its limits after its routes are built. A request that arrived
        with no application behind it declares neither bound, and is left to the ceiling
        this transport was built with.

        The import is deferred for the reason given on the refusal above, and is reached
        only while a body is being read, which is only ever while the framework that owns
        this class is running.
        """

        application = self._scope.get("app")
        if application is None:
            return None, None

        from ...runtime.execution import request_limits_of

        limits = request_limits_of(application)
        return limits.max_body_bytes, limits.max_upload_bytes

    def _query_string(self) -> str:
        return cast(bytes, self._scope.get("query_string", b"")).decode("latin-1")

    def _authority(self) -> tuple[str, int | None]:
        host_header = self.headers.get("host")
        if host_header is not None:
            host, _, port = host_header.partition(":")
            return host, int(port) if port.isdigit() else None
        server = self._scope.get("server")
        if server is None:
            return "", None
        host, port = cast("tuple[str, int | None]", server)
        return host, port


def from_asgi_request(request: HttpRequest | object) -> HttpRequest:
    """Return the neutral request contract for whatever the server handed over.

    A request that has already been wrapped is returned as it is, so wrapping twice
    never produces two views of one request with different state. A bare scope and
    receive pair - the two objects raw ASGI actually defines - is wrapped into one.
    """

    if isinstance(request, AsgiHttpRequest):
        return request
    if isinstance(request, tuple) and len(request) == 2:
        scope, receive = cast("tuple[Scope, Receive]", request)
        return AsgiHttpRequest(scope, receive)
    return cast(HttpRequest, request)


__all__ = (
    "DEFAULT_MAX_BODY_BYTES",
    "AsgiHttpRequest",
    "ClientDisconnected",
    "from_asgi_request",
)
