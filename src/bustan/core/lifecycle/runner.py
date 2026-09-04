"""Execution runner for module lifecycle stages."""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import cast

from ...common.types import ProviderScope
from ..errors import InvalidModuleError, LifecycleError
from ..ioc.container import Container
from ..ioc.registry import Binding
from ..ioc.scopes import DurableKey, DurableProvider
from ..module.dynamic import ModuleKey
from ..module.graph import ModuleGraph, ModuleNode
from ..utils import _display_name
from .hooks import LIFECYCLE_HOOK_NAMES

# The binding kinds that name an instance the framework builds. A value binding hands
# the framework an object that was built elsewhere and an alias is a second name for a
# token that is already bound, so neither is the framework's to initialize or destroy.
_CONSTRUCTED_KINDS = frozenset({"class", "factory"})


@dataclass(frozen=True, slots=True)
class ConstructedInstance:
    """One instance the container built, and the token it was built for."""

    token: object
    instance: object


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


def build_module_instance(module_cls: type[object], key: ModuleKey) -> object:
    """Build one module class, refusing a module the framework cannot build itself.

    The framework builds a module to read what it declares, and it has nothing to
    pass a constructor that asks for arguments, so such a module is refused by name
    rather than through a builtin ``TypeError`` that says neither which module nor
    why.
    """

    try:
        return module_cls()
    except TypeError as exc:
        raise InvalidModuleError(
            f"Could not build module {_display_name(key)}: {exc}. A module the framework "
            "builds must accept no constructor arguments"
        ) from exc


def instantiate_lifecycle_modules(nodes: tuple[ModuleNode, ...]) -> Mapping[ModuleKey, object]:
    """Create instances for modules that implement lifecycle hooks."""
    module_instances: dict[ModuleKey, object] = {}

    for node in nodes:
        if not _has_lifecycle_hooks(node.module):
            continue
        module_instances[node.key] = build_module_instance(node.module, node.key)

    return MappingProxyType(module_instances)


def _has_lifecycle_hooks(module_cls: type[object]) -> bool:
    """Return whether a module class implements at least one lifecycle hook."""
    return any(callable(getattr(module_cls, hook_name, None)) for hook_name in LIFECYCLE_HOOK_NAMES)


async def warm_up_providers(graph: ModuleGraph, container: Container) -> None:
    """Build every provider whose instance exists before the first request arrives.

    One awaited pass in graph order builds synchronous and asynchronous providers
    alike, so an application never has half its providers warmed in one order and
    half in another. Resolution builds a provider's dependencies before the
    provider itself, which is what makes the construction order this pass records
    dependency-first, and therefore what makes reversing it a safe teardown order.
    """

    for node in graph.nodes:
        for binding in node.bindings:
            if not _warms_at_startup(binding):
                continue
            await container.resolve_async(binding.token, module=node.key)


def _warms_at_startup(binding: Binding) -> bool:
    """Return whether a binding names an instance that exists before any request.

    A durable provider partitions its instances by a key it derives from the
    request. One that can derive a key with no request in flight has a partition
    belonging to the application itself, which is warmed here; one that cannot has
    only per-request partitions, which are created as requests arrive and still
    take part in every teardown stage.
    """

    if binding.scope is ProviderScope.SINGLETON:
        return True
    if binding.scope is not ProviderScope.DURABLE:
        return False

    # A durable binding whose target declares no usable context key hook is refused
    # while the graph is built, so a durable target always carries one.
    context_key_hook = cast(DurableProvider, binding.target).get_durable_context_key
    try:
        context_key_hook(None)
    except Exception:
        # The hook is the provider's own answer to "which partition is this?", and
        # a hook that refuses to answer without a request is saying the application
        # itself has no partition. Failing startup over that would refuse every
        # durable provider whose key comes from the request, which is most of them.
        return False
    return True


def constructed_instances(container: Container) -> tuple[ConstructedInstance, ...]:
    """Return the instances the container built, in construction order.

    Only a class or factory binding names an instance the framework built: an
    object handed over as a value arrived already built, and an alias is a second
    name for a token that is already bound. One object bound under two tokens
    appears once, under the token it was first built for, so it receives each
    lifecycle hook exactly once.

    Durable partitions come last because they are created while requests are being
    served, after every provider warmed at startup.
    """

    scope_manager = container.scope_manager
    seen: set[int] = set()
    constructed: list[ConstructedInstance] = []

    for singleton_key, instance in tuple(scope_manager.singletons.items()):
        _record(constructed, seen, container, singleton_key, instance)

    for durable_key, instance in tuple(scope_manager.durable_instances.items()):
        module_key, token, _partition = cast(DurableKey, durable_key)
        _record(constructed, seen, container, (module_key, token), instance)

    return tuple(constructed)


def _record(
    constructed: list[ConstructedInstance],
    seen: set[int],
    container: Container,
    binding_key: tuple[ModuleKey, object],
    instance: object,
) -> None:
    """Add one cached instance to the participants, unless it is already there."""

    binding = container.registry.get_binding(binding_key)
    if binding is None or binding.resolver_kind not in _CONSTRUCTED_KINDS:
        return
    if id(instance) in seen:
        return
    seen.add(id(instance))
    constructed.append(ConstructedInstance(token=binding_key[1], instance=instance))


async def run_provider_lifecycle_stage(
    container: Container,
    hook_name: str,
    *hook_arguments: object,
    reverse: bool = False,
    collect_errors: bool = False,
) -> tuple[LifecycleError, ...]:
    """Execute one lifecycle stage for the provider instances the container built.

    Instances are visited in construction (dependency-first) order; teardown stages
    pass ``reverse`` so dependents shut down before their dependencies.
    """

    participants = constructed_instances(container)
    if reverse:
        participants = tuple(reversed(participants))

    errors: list[LifecycleError] = []
    for participant in participants:
        hook = getattr(participant.instance, hook_name, None)
        if not callable(hook):
            continue
        try:
            result = hook(*hook_arguments)
            if inspect.isawaitable(result):
                await result
        except Exception as exc:
            error = LifecycleError(
                f"Provider lifecycle hook {_display_name(participant.token)}.{hook_name} "
                f"failed: {exc}"
            )
            error.__cause__ = exc
            if not collect_errors:
                raise error from exc
            errors.append(error)

    return tuple(errors)


async def run_init_stage(
    graph: ModuleGraph,
    container: Container,
    module_instances: Mapping[ModuleKey, object],
) -> None:
    """Warm the providers that exist before the first request, then initialize them."""

    await warm_up_providers(graph, container)
    await run_lifecycle_stage(graph.nodes, module_instances, "on_module_init")
    await run_provider_lifecycle_stage(container, "on_module_init")


async def run_init_hooks(graph: ModuleGraph, container: Container) -> Mapping[ModuleKey, object]:
    """Build the lifecycle modules and run initialization for them and the providers."""
    module_instances = instantiate_lifecycle_modules(graph.nodes)
    await run_init_stage(graph, container, module_instances)
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
