"""Scoped provider override helpers for tests."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import TypeVar, cast

from starlette.applications import Starlette

from ..container import ContainerAdapter

ResolvedT = TypeVar("ResolvedT")


@contextmanager
def override_provider(
    target: Starlette | ContainerAdapter,
    provider_cls: type[ResolvedT],
    replacement: ResolvedT,
    *,
    module_cls: type[object] | None = None,
) -> Iterator[None]:
    """Temporarily replace a provider for the duration of a context block."""

    container = _resolve_container(target)
    had_override = container.has_provider_override(provider_cls, module_cls=module_cls)
    previous_override: ResolvedT | None = None
    if had_override:
        previous_override = container.get_provider_override(provider_cls, module_cls=module_cls)

    container.set_provider_override(provider_cls, replacement, module_cls=module_cls)
    try:
        yield
    finally:
        if had_override:
            container.set_provider_override(
                provider_cls,
                cast(ResolvedT, previous_override),
                module_cls=module_cls,
            )
        else:
            container.clear_provider_override(provider_cls, module_cls=module_cls)


def _resolve_container(target: Starlette | ContainerAdapter) -> ContainerAdapter:
    if isinstance(target, ContainerAdapter):
        return target

    return cast(ContainerAdapter, target.state.bustan_container)