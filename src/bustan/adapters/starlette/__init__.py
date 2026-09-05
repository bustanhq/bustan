"""The Starlette transport adapter and the conversions it owns.

This package is the only place in ``bustan`` that imports Starlette. Everything the
framework needs from a transport it asks for through the adapter port, so nothing
here is imported unless an application actually chooses this adapter.
"""

from __future__ import annotations

from .adapter import StarletteAdapter
from .middleware import ConditionalMiddleware
from .requests import StarletteHttpRequest, from_starlette_request
from .responses import to_starlette_response
from .routes import build_starlette_routes

__all__ = (
    "ConditionalMiddleware",
    "StarletteAdapter",
    "StarletteHttpRequest",
    "build_starlette_routes",
    "from_starlette_request",
    "to_starlette_response",
)
