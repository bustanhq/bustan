"""Execution runner for module lifecycle stages."""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from types import MappingProxyType

from ..errors import LifecycleError
from ..module.dynamic import ModuleKey
from ..module.graph import ModuleNode
from ..utils import _display_name
from .hooks import LifecycleHookName


async def run_lifecycle_stage(
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


def instantiate_lifecycle_modules(nodes: tuple[ModuleNode, ...]) -> Mapping[ModuleKey, object]:
    """Create instances for modules that implement lifecycle hooks."""
    module_instances: dict[ModuleKey, object] = {}

    for node in nodes:
        if not _has_lifecycle_hooks(node.module):
            continue

        try:
            module_instances[node.key] = node.module()
        except TypeError as exc:
            raise LifecycleError(
                f"Could not instantiate module {_display_name(node.key)} for lifecycle hooks: {exc}"
            ) from exc

    return MappingProxyType(module_instances)


def _has_lifecycle_hooks(module_cls: type[object]) -> bool:
    """Return whether a module class implements at least one lifecycle hook."""
    return any(callable(getattr(module_cls, hook_name, None)) for hook_name in LifecycleHookName)
