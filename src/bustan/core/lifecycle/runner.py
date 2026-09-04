"""Execution runner for module lifecycle stages."""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from types import MappingProxyType

from ...common.types import ProviderScope
from ..errors import LifecycleError
from ..ioc.container import Container
from ..module.dynamic import ModuleKey
from ..module.graph import ModuleGraph, ModuleNode
from ..utils import _display_name
from .hooks import LIFECYCLE_HOOK_NAMES


async def run_lifecycle_stage(
    nodes: tuple[ModuleNode, ...],
    module_instances: Mapping[ModuleKey, object],
    hook_name: str,
    *hook_arguments: object,
    collect_errors: bool = False,
) -> tuple[LifecycleError, ...]:
    """Execute one lifecycle stage for every module in the provided order.

    With ``collect_errors`` (the teardown mode), a failing hook does not
    prevent the remaining hooks from running; the failures are returned so
    the caller can aggregate them once teardown has completed.
    """

    errors: list[LifecycleError] = []
    for node in nodes:
        module_instance = module_instances.get(node.key)
        if module_instance is None:
            continue

        hook = getattr(module_instance, hook_name, None)
        if hook is None:
            continue

        try:
            result = hook(*hook_arguments)
            if inspect.isawaitable(result):
                await result
        except Exception as exc:
            error = LifecycleError(
                f"Lifecycle hook {_display_name(node.key)}.{hook_name} failed: {exc}"
            )
            error.__cause__ = exc
            if not collect_errors:
                raise error from exc
            errors.append(error)

    return tuple(errors)


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
    return any(callable(getattr(module_cls, hook_name, None)) for hook_name in LIFECYCLE_HOOK_NAMES)


def instantiate_lifecycle_providers(graph: ModuleGraph, container: Container) -> None:
    """Pre-resolve singleton providers so provider-level lifecycle hooks can run."""
    for node in graph.nodes:
        for binding in node.bindings:
            if binding.scope not in (ProviderScope.SINGLETON,):
                continue
            container.resolve(binding.token, module=node.key)


async def run_provider_lifecycle_stage(
    container: Container,
    hook_name: str,
    *hook_arguments: object,
    reverse: bool = False,
    collect_errors: bool = False,
) -> tuple[LifecycleError, ...]:
    """Execute one lifecycle stage for resolved singleton providers.

    Singletons are recorded in creation (dependency-first) order; teardown
    stages pass ``reverse`` so dependents shut down before their dependencies.
    """
    instances = tuple(container.scope_manager.singletons.values())
    if reverse:
        instances = tuple(reversed(instances))

    errors: list[LifecycleError] = []
    for instance in instances:
        hook = getattr(instance, hook_name, None)
        if hook is None:
            continue
        try:
            result = hook(*hook_arguments)
            if inspect.isawaitable(result):
                await result
        except Exception as exc:
            error = LifecycleError(
                f"Provider lifecycle hook {type(instance).__name__}.{hook_name} failed: {exc}"
            )
            error.__cause__ = exc
            if not collect_errors:
                raise error from exc
            errors.append(error)

    return tuple(errors)


async def run_init_hooks(graph: ModuleGraph, container: Container) -> Mapping[ModuleKey, object]:
    """Run initialization hooks for modules and singleton providers."""
    module_instances = instantiate_lifecycle_modules(graph.nodes)
    instantiate_lifecycle_providers(graph, container)
    await run_lifecycle_stage(graph.nodes, module_instances, "on_module_init")
    await run_provider_lifecycle_stage(container, "on_module_init")
    return module_instances


async def run_bootstrap_hooks(
    graph: ModuleGraph,
    container: Container,
    module_instances: Mapping[ModuleKey, object],
) -> None:
    """Run bootstrap hooks after initialization completes."""
    await run_lifecycle_stage(graph.nodes, module_instances, "on_application_bootstrap")
    await run_provider_lifecycle_stage(container, "on_application_bootstrap")


async def run_before_shutdown_hooks(
    graph: ModuleGraph,
    container: Container,
    module_instances: Mapping[ModuleKey, object],
    signal: str | None = None,
) -> tuple[LifecycleError, ...]:
    """Run pre-shutdown hooks in reverse order, collecting failures."""

    reversed_nodes = tuple(reversed(graph.nodes))
    errors = await run_lifecycle_stage(
        reversed_nodes,
        module_instances,
        "before_application_shutdown",
        signal,
        collect_errors=True,
    )
    return errors + await run_provider_lifecycle_stage(
        container,
        "before_application_shutdown",
        signal,
        reverse=True,
        collect_errors=True,
    )


async def run_shutdown_hooks(
    graph: ModuleGraph,
    container: Container,
    module_instances: Mapping[ModuleKey, object],
    signal: str | None = None,
) -> tuple[LifecycleError, ...]:
    """Run application shutdown hooks in reverse order, collecting failures."""
    reversed_nodes = tuple(reversed(graph.nodes))
    errors = await run_lifecycle_stage(
        reversed_nodes,
        module_instances,
        "on_application_shutdown",
        signal,
        collect_errors=True,
    )
    return errors + await run_provider_lifecycle_stage(
        container,
        "on_application_shutdown",
        signal,
        reverse=True,
        collect_errors=True,
    )


async def run_destroy_hooks(
    graph: ModuleGraph,
    container: Container,
    module_instances: Mapping[ModuleKey, object],
) -> tuple[LifecycleError, ...]:
    """Run teardown hooks in reverse order, collecting failures."""
    reversed_nodes = tuple(reversed(graph.nodes))
    errors = await run_lifecycle_stage(
        reversed_nodes,
        module_instances,
        "on_module_destroy",
        collect_errors=True,
    )
    return errors + await run_provider_lifecycle_stage(
        container,
        "on_module_destroy",
        reverse=True,
        collect_errors=True,
    )
