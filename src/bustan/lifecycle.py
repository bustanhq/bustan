"""Starlette lifespan integration for module lifecycle hooks."""

from __future__ import annotations

import inspect
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from types import MappingProxyType

from starlette.applications import Starlette
from starlette.types import StatelessLifespan

from .errors import LifecycleError
from .metadata import ModuleKey
from .module_graph import ModuleGraph, ModuleNode
from .utils import _display_name

LifecycleHookName: tuple[str, ...] = (
    "on_module_init",
    "on_app_startup",
    "on_app_shutdown",
    "on_module_destroy",
)


def build_lifespan(
    module_graph: ModuleGraph,
) -> StatelessLifespan[Starlette]:
    """Build the Starlette lifespan handler for the module graph."""

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        module_instances = _instantiate_lifecycle_modules(module_graph)
        app.state.bustan_module_instances = module_instances

        await _run_lifecycle_stage(module_graph.nodes, module_instances, "on_module_init")
        await _run_lifecycle_stage(module_graph.nodes, module_instances, "on_app_startup")

        try:
            yield
        finally:
            await _run_lifecycle_stage(
                tuple(reversed(module_graph.nodes)),
                module_instances,
                "on_app_shutdown",
            )
            await _run_lifecycle_stage(
                tuple(reversed(module_graph.nodes)),
                module_instances,
                "on_module_destroy",
            )

    return lifespan


def _instantiate_lifecycle_modules(module_graph: ModuleGraph) -> Mapping[ModuleKey, object]:
    module_instances: dict[ModuleKey, object] = {}

    for node in module_graph.nodes:
        # Plain modules stay uninstantiated unless they actually expose hooks.
        if not _has_lifecycle_hooks(node.module):
            continue

        try:
            module_instances[node.key] = node.module()
        except TypeError as exc:
            raise LifecycleError(
                f"Could not instantiate module {_display_name(node.key)} for lifecycle hooks: {exc}"
            ) from exc

    return MappingProxyType(module_instances)


async def _run_lifecycle_stage(
    nodes: tuple[ModuleNode, ...],
    module_instances: Mapping[ModuleKey, object],
    hook_name: str,
) -> None:
    """Execute one lifecycle stage for every module in the provided order."""

    for node in nodes:
        module_instance = module_instances.get(node.key)
        if module_instance is None:
            continue

        hook = getattr(module_instance, hook_name, None)
        if hook is None:
            continue

        try:
            result = hook()
            if inspect.isawaitable(result):
                await result
        except Exception as exc:
            raise LifecycleError(
                f"Lifecycle hook {_display_name(node.key)}.{hook_name} failed: {exc}"
            ) from exc


def _has_lifecycle_hooks(module_cls: type[object]) -> bool:
    return any(callable(getattr(module_cls, hook_name, None)) for hook_name in LifecycleHookName)
