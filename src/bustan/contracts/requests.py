"""Adapter-neutral request contracts.

Nothing in this module may import from the rest of ``bustan`` or from any web
framework: it is the vocabulary both the framework runtime and every transport
adapter are written against, so a dependency here would put a server library back
on the framework's critical path.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, cast, runtime_checkable

# Reserved on the state namespace for the typed slots, so that the same request always
# yields the same ``RequestSlots`` however many request wrappers are built around it.
REQUEST_SLOTS_ATTR = "bustan_request_slots"


@dataclass(frozen=True, slots=True)
class HttpClientInfo:
    """Normalized client connection details."""

    host: str | None = None
    port: int | None = None


@runtime_checkable
class HttpUrl(Protocol):
    """Minimal URL surface required by the framework runtime."""

    @property
    def path(self) -> str:
        raise NotImplementedError


@runtime_checkable
class HttpQueryParams(Protocol):
    """Minimal multi-value query parameter surface used by parameter binding."""

    def getlist(self, key: str) -> list[str]:
        raise NotImplementedError

    def __contains__(self, key: object) -> bool:
        raise NotImplementedError

    def __getitem__(self, key: str) -> str:
        raise NotImplementedError


@runtime_checkable
class HttpFormData(Protocol):
    """Minimal form-data surface used by parameter binding."""

    def get(self, key: str, default: object | None = None) -> object | None:
        raise NotImplementedError

    def getlist(self, key: str) -> list[object]:
        raise NotImplementedError


@runtime_checkable
class HttpRequestState(Protocol):
    """Mutable attribute namespace that lives exactly as long as one request.

    Anything the framework has to carry from one stage of a request to a later one
    is stored here, so the namespace is open rather than a fixed set of fields: the
    request-scoped provider cache and controller cache, the request context
    identifier, the principal a guard authenticated, and the rate limit counters the
    throttler writes for the response writer to read back. Attribute names beginning
    with ``bustan_`` are reserved for the framework; an application is free to use
    any other name.

    Reads of an attribute that was never written raise ``AttributeError``, which is
    what lets ``getattr(state, name, default)`` and ``hasattr`` distinguish "not set
    yet" from "set to ``None``".

    A read is typed ``Any`` because the namespace is open: what comes back is whatever
    the guard, interceptor or application that wrote the attribute put there, and no
    narrower type is true of every slot. The declaration that matters is the namespace
    itself, which is this protocol rather than an untyped request attribute.
    """

    def __getattr__(self, name: str, /) -> Any:
        raise NotImplementedError

    def __setattr__(self, name: str, value: object, /) -> None:
        raise NotImplementedError

    def __delattr__(self, name: str, /) -> None:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    """What a throttler decided about one request.

    A guard writes this once it has counted the request; the response writer reads it
    back to emit the ``X-RateLimit-*`` headers, and the exception filter reads
    ``exceeded`` to tell a request refused for rate limiting apart from one refused for
    any other reason. ``reset`` is the seconds remaining until the window the count was
    taken in ends.
    """

    limit: int
    remaining: int
    reset: int
    exceeded: bool


@dataclass(slots=True)
class RequestSlots:
    """The typed values the framework carries from one stage of a request to a later one.

    Unlike the open state namespace, every slot here is declared and typed, so a stage
    that writes one and a stage that reads it are checked against the same declaration
    rather than agreeing on an attribute name by convention. A slot is ``None`` until
    the stage that owns it has run.
    """

    rate_limit: RateLimitDecision | None = None


def request_slots(state: HttpRequestState) -> RequestSlots:
    """Return the typed slots belonging to the request that owns *state*.

    The slots are created on first use and kept on the state namespace, so every
    request wrapper built around one request sees the same object and a write made
    through one is visible through the next.
    """

    slots = getattr(state, REQUEST_SLOTS_ATTR, None)
    if slots is None:
        slots = RequestSlots()
        setattr(state, REQUEST_SLOTS_ATTR, slots)
    return cast(RequestSlots, slots)


@runtime_checkable
class HttpRequest(Protocol):
    """Adapter-neutral request surface used by framework runtime code."""

    @property
    def native_request(self) -> object:
        raise NotImplementedError

    @property
    def method(self) -> str:
        raise NotImplementedError

    @property
    def path(self) -> str:
        raise NotImplementedError

    @property
    def url(self) -> HttpUrl:
        raise NotImplementedError

    @property
    def headers(self) -> Mapping[str, str]:
        raise NotImplementedError

    @property
    def query_params(self) -> HttpQueryParams:
        raise NotImplementedError

    @property
    def path_params(self) -> Mapping[str, str]:
        raise NotImplementedError

    @property
    def cookies(self) -> Mapping[str, str]:
        raise NotImplementedError

    @property
    def state(self) -> HttpRequestState:
        raise NotImplementedError

    @property
    def slots(self) -> RequestSlots:
        raise NotImplementedError

    @property
    def client(self) -> HttpClientInfo | None:
        raise NotImplementedError

    @property
    def app(self) -> Any:
        raise NotImplementedError

    async def body(self) -> bytes:
        raise NotImplementedError

    async def json(self) -> object:
        raise NotImplementedError

    async def form(self) -> HttpFormData:
        raise NotImplementedError


def as_http_request(request: HttpRequest | object) -> HttpRequest:
    """Return *request* as the neutral request contract.

    A transport adapter converts its own request object exactly once, at the edge, so
    everything downstream of that conversion already holds an :class:`HttpRequest`.
    This narrows the loosely typed argument the older entry points still accept; it
    performs no conversion and reaches for no transport.
    """

    return cast(HttpRequest, request)


__all__ = (
    "HttpClientInfo",
    "HttpFormData",
    "HttpQueryParams",
    "HttpRequest",
    "HttpRequestState",
    "HttpUrl",
    "RateLimitDecision",
    "RequestSlots",
    "as_http_request",
    "request_slots",
)
