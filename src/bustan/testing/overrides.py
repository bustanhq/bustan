"""Scoped provider override helpers for tests."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import cast

from starlette.applications import Starlette
from ..application import Application

from ..container import Container


@contextmanager
def override_provider(
    target: Starlette | Application | Container,
    token: object,
    replacement: object,
    *,
    module_cls: type[object] | None = None,
) -> Iterator[None]:
    """Temporarily replace a provider for the duration of a context block."""

    container = _resolve_container(target)
    had_override = container.has_override(token, module=module_cls)
    previous_override: object = None
    if had_override:
        previous_override = container.get_override(token, module=module_cls)

    container.override(token, replacement, module=module_cls)
    try:
        yield
    finally:
        if had_override:
            container.override(token, previous_override, module=module_cls)
        else:
            container.clear_override(token, module=module_cls)


def _resolve_container(target: Starlette | Application | Container) -> Container:
    if isinstance(target, Container):
        return target
    if isinstance(target, Application):
        return target._container

    return cast(Container, getattr(target.state, "bustan_container"))
