"""The vocabulary the framework and its transport adapters share.

Every Protocol and neutral value type on the request path lives here, and this package
imports nothing from the rest of ``bustan`` and nothing from any web framework. That
one-way dependency is the point: framework code and adapter code can both be read,
tested and type checked against these declarations without either one reaching for the
other, and installing ``bustan`` does not require a server library to be present.

The adapter port lives here for the same reason. It is the one declaration both sides
must agree on, so putting it anywhere else would mean an adapter importing framework
code to learn what it is expected to implement.
"""

from __future__ import annotations

from .adapter import (
    AbstractHttpAdapter,
    AdapterCapabilities,
    AdapterRoute,
    HttpResponseValue,
    RouteHandler,
)
from .requests import (
    HttpClientInfo,
    HttpFormData,
    HttpQueryParams,
    HttpRequest,
    HttpRequestState,
    HttpUrl,
    NativeHttpRequest,
    RateLimitDecision,
    RequestSlots,
    as_http_request,
    names_native_request,
    request_slots,
)
from .responses import HttpFileResponse, HttpResponse, HttpStreamResponse, NativeHttpResponse
from .values import Headers, QueryParams, RequestState, Url

__all__ = (
    "AbstractHttpAdapter",
    "AdapterCapabilities",
    "AdapterRoute",
    "Headers",
    "HttpClientInfo",
    "HttpFileResponse",
    "HttpFormData",
    "HttpQueryParams",
    "HttpRequest",
    "HttpRequestState",
    "HttpResponse",
    "HttpResponseValue",
    "HttpStreamResponse",
    "HttpUrl",
    "NativeHttpRequest",
    "NativeHttpResponse",
    "QueryParams",
    "RateLimitDecision",
    "RequestSlots",
    "RequestState",
    "RouteHandler",
    "Url",
    "as_http_request",
    "names_native_request",
    "request_slots",
)
