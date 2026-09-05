"""The neutral request contract, backed by one Starlette request."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from starlette.requests import Request

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

if TYPE_CHECKING:
    from collections.abc import Mapping


class StarletteHttpRequest:
    """One Starlette request, seen through the framework's neutral request contract.

    Every property returns a neutral value, so framework code that reads a request
    never receives a Starlette object and can be exercised without Starlette present.
    The two exceptions are deliberate: ``native_request`` is the declared escape hatch
    for code that has decided it wants the transport's own object, and ``form``
    returns the transport's form data because an uploaded file has no representation
    that is not the transport's.

    State is shared rather than copied. The neutral namespace is a view over the same
    storage the Starlette request keeps its own state in, so an attribute written
    through one wrapper is visible through the next wrapper built around the same
    request, and to anything that reads the Starlette request directly.
    """

    __slots__ = ("_request", "_state")

    def __init__(self, request: Request) -> None:
        self._request = request
        self._state: RequestState | None = None

    @property
    def native_request(self) -> Request:
        """The Starlette request this wraps."""

        return self._request

    @property
    def method(self) -> str:
        """The HTTP method, upper case."""

        return self._request.method

    @property
    def path(self) -> str:
        """The request path, without the query string."""

        return self._request.url.path

    @property
    def url(self) -> Url:
        """The request URL as plain data."""

        native = self._request.url
        return Url(
            scheme=native.scheme,
            host=native.hostname or "",
            port=native.port,
            path=native.path,
            query_string=native.query,
            fragment=native.fragment,
        )

    @property
    def headers(self) -> Mapping[str, str]:
        """The request headers, looked up without regard to case."""

        return Headers(self._request.headers.items())

    @property
    def query_params(self) -> QueryParams:
        """The decoded query string, keeping every value of a repeated key."""

        return QueryParams(self._request.query_params.multi_items())

    @property
    def path_params(self) -> Mapping[str, str]:
        """The parameters the router captured from the path."""

        return dict(self._request.path_params)

    @property
    def cookies(self) -> Mapping[str, str]:
        """The cookies the request carried."""

        return dict(self._request.cookies)

    @property
    def state(self) -> HttpRequestState:
        """The open per-request namespace, sharing storage with the Starlette request."""

        if self._state is None:
            scope = self._request.scope
            # Starlette keeps its own request state in this scope entry, so a view over
            # it is the same storage rather than a second copy that would drift.
            scope.setdefault("state", {})
            self._state = RequestState(scope["state"])
        return self._state

    @property
    def slots(self) -> RequestSlots:
        """The framework's typed per-request slots, created on first use."""

        return request_slots(self.state)

    @property
    def client(self) -> HttpClientInfo | None:
        """Who connected, when the transport reported it."""

        client = self._request.client
        if client is None:
            return None
        return HttpClientInfo(host=client.host, port=client.port)

    @property
    def app(self) -> object:
        """The application object the transport attached to the request."""

        return self._request.app

    async def body(self) -> bytes:
        """Read the whole request body."""

        return await self._request.body()

    async def json(self) -> object:
        """Read the request body and decode it as JSON."""

        return await self._request.json()

    async def form(self) -> HttpFormData:
        """Read the request body as form data, uploaded files included."""

        return cast(HttpFormData, await self._request.form())


def from_starlette_request(request: HttpRequest | Request | object) -> HttpRequest:
    """Return the neutral request contract for whatever the transport handed over.

    A request that has already been wrapped is returned as it is, so wrapping twice
    never produces two views of one request with different state.
    """

    if isinstance(request, StarletteHttpRequest):
        return request
    if isinstance(request, Request):
        return StarletteHttpRequest(request)
    return cast(HttpRequest, request)


__all__ = (
    "StarletteHttpRequest",
    "from_starlette_request",
)
