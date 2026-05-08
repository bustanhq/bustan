"""Public context-id helpers built on the finalized scope semantics."""

from __future__ import annotations

from dataclasses import dataclass

from starlette.requests import Request

from ..core.ioc.scopes import DurableProvider
from ..core.module.dynamic import ModuleKey
from ..core.utils import _display_name


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
    return ContextId(scope="request", value=str(id(request)))


def durable_context_id(provider: type[DurableProvider], request: Request | None) -> ContextId:
    return ContextId(
        scope="durable",
        value=f"{provider.__name__}:{provider.get_durable_context_key(request)!r}",
    )
