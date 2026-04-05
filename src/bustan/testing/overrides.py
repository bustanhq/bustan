"""Scoped provider override helpers for tests."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import cast

from starlette.applications import Starlette

from ..container import ContainerAdapter


@contextmanager
def override_provider(
    target: Starlette | ContainerAdapter,
    token: object,
    replacement: object,
    *,
    module_cls: type[object] | None = None,
) -> Iterator[None]:
    """Temporarily replace a provider for the duration of a context block."""

    container = _resolve_container(target)
    had_override = container.has_provider_override(token, module_cls=module_cls)
    previous_override: object = None
    if had_override:
        previous_override = container.get_provider_override(token, module_cls=module_cls)

    container.set_provider_override(token, replacement, module_cls=module_cls)
    try:
        yield
    finally:
        if had_override:
            container.set_provider_override(token, previous_override, module_cls=module_cls)
        else:
            container.clear_provider_override(token, module_cls=module_cls)


def _resolve_container(target: Starlette | ContainerAdapter) -> ContainerAdapter:
    if isinstance(target, ContainerAdapter):
        return target

    return cast(ContainerAdapter, target.state.bustan_container)