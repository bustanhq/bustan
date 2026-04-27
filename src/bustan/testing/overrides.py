"""Scoped provider and pipeline override helpers for tests."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import cast

from starlette.applications import Starlette
from ..app.application import Application
from ..core.ioc.container import Container
from ..pipeline.metadata import PipelineMetadata


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


@dataclass(slots=True)
class PipelineOverrideRegistry:
    """Stores replacements for pipeline classes in test contexts."""

    guards: dict[object, object]
    pipes: dict[object, object]
    interceptors: dict[object, object]
    filters: dict[object, object]

    def __init__(self) -> None:
        self.guards = {}
        self.pipes = {}
        self.interceptors = {}
        self.filters = {}

    def apply_to_metadata(self, metadata: PipelineMetadata) -> PipelineMetadata:
        """Return metadata with known pipeline components replaced."""
        return PipelineMetadata(
            guards=tuple(self.guards.get(component, component) for component in metadata.guards),
            pipes=tuple(self.pipes.get(component, component) for component in metadata.pipes),
            interceptors=tuple(
                self.interceptors.get(component, component)
                for component in metadata.interceptors
            ),
            filters=tuple(self.filters.get(component, component) for component in metadata.filters),
        )
