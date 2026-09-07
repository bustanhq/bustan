"""The neutral request contract, backed by one raw ASGI connection."""

from __future__ import annotations

import json
from http.cookies import SimpleCookie
from typing import TYPE_CHECKING, cast

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

# How many body bytes this transport will read before it stops reading. A body is read
# into memory to be parsed, so an unauthenticated caller could otherwise grow that
# buffer without limit.
#
# The number is twice the largest body the framework's own request limits accept under
# their defaults, and the doubling is the point rather than the value: a transport that
# stopped reading below a limit the application had set would refuse a request the
# application was configured to serve, and would answer it with a bound nobody chose.
# The framework's limit is what answers a caller; this bounds only what a caller already
# past every framework limit can make one process buffer. A deployment that raises the
# framework's limits above this raises this too, by building the adapter with a
# ``max_body_bytes`` of its own. The figure is written out rather than derived from the
# framework's, because reading it from there would make this package import the
# framework at module scope and it deliberately imports nothing but the request
# contracts.
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
    cannot be rewound and more than one stage of a request may ask for it.
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
        """Read the whole request body, refusing one larger than the limit."""

        if self._body is None:
            self._body = await self._read_body()
        return self._body

    async def json(self) -> object:
        """Read the request body and decode it as JSON."""

        return json.loads(await self.body())

    async def form(self) -> HttpFormData:
        """Read the request body as form data, uploaded files included."""

        return parse_form_body(await self.body(), self.headers.get("content-type"))

    def set_path_params(self, path_params: Mapping[str, str]) -> None:
        """Record what a router captured from the path, before the handler is called."""

        self._path_params = dict(path_params)

    async def _read_body(self) -> bytes:
        chunks: list[bytes] = []
        received = 0
        more = True
        while more:
            message: Message = await self._receive()
            if message.get("type") == "http.disconnect":
                raise ClientDisconnected("The client disconnected before its body arrived")
            chunk = cast(bytes, message.get("body", b""))
            received += len(chunk)
            if self._max_body_bytes is not None and received > self._max_body_bytes:
                # The framework's own refusal rather than one of this package's, so that
                # the filter which renders a limit refusal recognises it: a caller who
                # sent too much is told so, instead of being told the server broke and
                # having the refusal logged as a fault. The import is made here rather
                # than at module scope because this package imports nothing but the
                # request contracts, and a body is only ever refused while the framework
                # that owns this class is already running.
                from ...runtime.params import RequestBodyTooLargeError

                # The bytes already counted are not reported, because reading on to total
                # them is the cost the limit exists to refuse to pay.
                raise RequestBodyTooLargeError(
                    f"The request body carries more than the {self._max_body_bytes} byte limit"
                )
            chunks.append(chunk)
            more = bool(message.get("more_body", False))
        return b"".join(chunks)

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
