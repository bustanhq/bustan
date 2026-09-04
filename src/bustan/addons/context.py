"""Public context-id helpers built on the finalized scope semantics."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from starlette.requests import Request

from ..core.ioc.scopes import DurableProvider
from ..core.module.dynamic import ModuleKey
from ..core.utils import _display_name

# Where a request keeps the identifier minted for it. It lives on the request rather
# than in a table the framework owns, so it is released exactly when the request is
# and no bookkeeping can outlive what it names.
REQUEST_CONTEXT_ID_ATTR = "bustan_request_context_id"


@dataclass(frozen=True, slots=True)
class ContextId:
    """Stable scope-qualified context identifier."""

    scope: str
    value: str


def application_context_id(module: ModuleKey | type[object]) -> ContextId:
    return ContextId(scope="application", value=_display_name(module))


def request_context_id(request: Request | None) -> ContextId:
    if request is None:
        return ContextId(scope="request", value="none")

    # An identifier for a request has to be unique to it and stable for its whole life.
    # CPython reuses the address of an object it has collected, so id(request) is only
    # the first of those while the request is alive: sequential requests are handed the
    # same value one after another, and anything keyed on it - a log correlation, a
    # cache, a rate-limit bucket - attributes one caller's activity to the next. A
    # freshly generated value is unique because it has never been used before, and is
    # stable because it is kept on the request and read back by every later call.
    stored = getattr(request.state, REQUEST_CONTEXT_ID_ATTR, None)
    if isinstance(stored, str):
        return ContextId(scope="request", value=stored)

    minted = uuid4().hex
    setattr(request.state, REQUEST_CONTEXT_ID_ATTR, minted)
    return ContextId(scope="request", value=minted)


def durable_context_id(provider: type[DurableProvider], request: Request | None) -> ContextId:
    return ContextId(
        scope="durable",
        value=f"{provider.__name__}:{provider.get_durable_context_key(request)!r}",
    )
