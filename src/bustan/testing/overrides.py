"""Scoped provider and pipeline override helpers for tests."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from ..app.application import Application
from ..core.errors import ProviderResolutionError
from ..core.ioc.container import Container
from ..core.utils import _qualname
from ..pipeline.metadata import PipelineMetadata


@contextmanager
def override_provider(
    target: object,
    token: object,
    replacement: object,
    *,
    module_cls: type[object] | None = None,
) -> Iterator[None]:
    """Temporarily replace a provider, before the application it belongs to starts.

    ``target`` is the container to override in, the ``Application`` holding it, or the
    server object it was assembled with, which carries the container on its own state
    namespace. Anything else raises ``TypeError``.

    An override belongs to bootstrap. It does not stand beside the provider it
    replaces for the length of the block; it replaces it for the whole application,
    including every instance already built from it. Against an application that has
    started, that is refused rather than half honoured: the singletons startup built
    from the real provider are the ones still being served, so a block that appeared
    to swap a dependency would have swapped nothing. Assemble the application with the
    replacement instead, with
    ``await create_testing_module(RootModule).override_provider(token).use_value(...).compile()``.
    """

    container = _resolve_container(target)
    _refuse_started_application(container, token)
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


def _refuse_started_application(container: Container, token: object) -> None:
    """Refuse a scoped override against an application that is already running.

    The refusal names the supported replacement rather than only the rule, because a
    suite reaching this has a working test that has to be written a different way.
    """

    if not container.override_manager.started:
        return
    raise ProviderResolutionError(
        f"{_qualname(token)} cannot be overridden while the application is running. "
        "An override replaces a provider for the whole application, including the "
        "instances built from it, so every override must be registered before startup. "
        "Build the application with the replacement instead, through "
        "create_testing_module(RootModule).override_provider(token).use_value(...) "
        "and its compile()"
    )


def _resolve_container(target: object) -> Container:
    if isinstance(target, Container):
        return target
    if isinstance(target, Application):
        return target._container

    # A server object carries the container it was assembled with on its own state
    # namespace, which is how one is recognised without knowing whose server it is.
    container = getattr(getattr(target, "state", None), "bustan_container", None)
    if isinstance(container, Container):
        return container
    raise TypeError("override_provider target does not expose a Bustan container")


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
                self.interceptors.get(component, component) for component in metadata.interceptors
            ),
            filters=tuple(self.filters.get(component, component) for component in metadata.filters),
        )
