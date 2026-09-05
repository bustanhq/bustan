"""A transport adapter over raw ASGI, written without a web framework.

The framework's claim to be server agnostic is only as good as the number of transports
that have actually implemented its adapter port. This package implements it against the
ASGI specification and the standard library, and nothing else: no Starlette, no other
framework, nothing that is not already installed with Python. What that buys is a second
implementation whose failures are informative - anything the framework needs from a
transport that ASGI alone cannot supply fails here, loudly, at the moment it is added.
"""

from __future__ import annotations

from .adapter import AsgiAdapter
from .application import AsgiApplication, Lifespan
from .forms import FormData, UploadFile, parse_form_body
from .lifespan import LifespanFailed, LifespanRunner
from .requests import (
    DEFAULT_MAX_BODY_BYTES,
    AsgiHttpRequest,
    ClientDisconnected,
    RequestBodyTooLarge,
    from_asgi_request,
)
from .responses import (
    AsgiFileResponse,
    AsgiResponse,
    AsgiResponseValue,
    AsgiStreamResponse,
    to_asgi_response,
)
from .routing import AsgiRoute, AsgiRouter, build_asgi_routes, compile_path
from .server import AsgiServer, HttpParseError
from .testclient import AsgiTestClient, AsgiTestResponse
from .types import AsgiApp, Message, Receive, Scope, Send

__all__ = (
    "DEFAULT_MAX_BODY_BYTES",
    "AsgiAdapter",
    "AsgiApp",
    "AsgiApplication",
    "AsgiFileResponse",
    "AsgiHttpRequest",
    "AsgiResponse",
    "AsgiResponseValue",
    "AsgiRoute",
    "AsgiRouter",
    "AsgiServer",
    "AsgiStreamResponse",
    "AsgiTestClient",
    "AsgiTestResponse",
    "ClientDisconnected",
    "FormData",
    "HttpParseError",
    "Lifespan",
    "LifespanFailed",
    "LifespanRunner",
    "Message",
    "Receive",
    "RequestBodyTooLarge",
    "Scope",
    "Send",
    "UploadFile",
    "build_asgi_routes",
    "compile_path",
    "from_asgi_request",
    "parse_form_body",
    "to_asgi_response",
)
