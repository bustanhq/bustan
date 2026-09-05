"""The vocabulary the framework and its transport adapters share.

Every Protocol and neutral value type on the request path lives here, and this package
imports nothing from the rest of ``bustan`` and nothing from any web framework. That
one-way dependency is the point: framework code and adapter code can both be read,
tested and type checked against these declarations without either one reaching for the
other, and installing ``bustan`` does not require a server library to be present.
"""

from __future__ import annotations

from .requests import (
    HttpClientInfo,
    HttpFormData,
    HttpQueryParams,
    HttpRequest,
    HttpRequestState,
    HttpUrl,
)
from .responses import HttpFileResponse, HttpResponse, HttpStreamResponse
from .values import QueryParams, Url

__all__ = (
    "HttpClientInfo",
    "HttpFileResponse",
    "HttpFormData",
    "HttpQueryParams",
    "HttpRequest",
    "HttpRequestState",
    "HttpResponse",
    "HttpStreamResponse",
    "HttpUrl",
    "QueryParams",
    "Url",
)
