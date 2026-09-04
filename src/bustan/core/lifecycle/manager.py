"""Shared application lifecycle orchestration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from ..errors import LifecycleError
from ..ioc.container import Container
from ..module.dynamic import ModuleKey
from ..module.graph import ModuleGraph
from .runner import (
    instantiate_lifecycle_modules,
    run_before_shutdown_hooks,
    run_bootstrap_hooks,
    run_destroy_hooks,
    run_init_stage,
    run_shutdown_hooks,
)


class LifecycleErrorGroup(LifecycleError, ExceptionGroup[LifecycleError]):
    """Every hook that failed during one teardown, raised together.

    Teardown runs each stage to completion so that one failing hook cannot leak
    every other component's resources, which means a single shutdown can produce
    more than one failure. Each member names the hook that failed and keeps the
    exception it was raised from as its ``__cause__``, so no traceback is lost to
    the aggregation.
    """


@dataclass(slots=True)
class LifecycleState:
    """Mutable lifecycle state owned by one application context.

    ``closed`` records that a startup was undone by a completed teardown. It is not
    a terminal state: startup may run again, and doing so begins a new cycle with
    every cache empty.
    """

    initialized: bool = False
    closed: bool = False
    module_instances: Mapping[ModuleKey, object] = field(default_factory=dict)


class LifecycleManager:
    """Coordinate startup and shutdown across HTTP and standalone apps."""

    def __init__(self, module_graph: ModuleGraph, container: Container) -> None:
        self._module_graph = module_graph
        self._container = container
        self._state = LifecycleState()

    @property
    def state(self) -> LifecycleState:
        return self._state

    async def startup(self) -> Mapping[ModuleKey, object]:
        """Build every eager provider and run the startup stages over what was built.

        A stage that fails part-way tears down whatever startup had already built,
        in reverse construction order, before the failure propagates: the caller
        never inherits a half-open application. The failure that propagates is the
        one that stopped startup, with any hook that also failed while undoing it
        recorded on it as a note.
        """

        if self._state.initialized:
            return self._state.module_instances

        # Modules are built before any hook runs, so a module that cannot be built
        # has opened nothing and leaves nothing to undo.
        module_instances = instantiate_lifecycle_modules(self._module_graph.nodes)
        # Recorded before the first provider is built: from here on teardown reads
        # what has been built out of this state and the container's caches.
        self._state = LifecycleState(module_instances=module_instances)

        try:
            await run_init_stage(self._module_graph, self._container, module_instances)
            await run_bootstrap_hooks(self._module_graph, self._container, module_instances)
        except Exception as failure:
            for error in await self._tear_down(signal=None):
                failure.add_note(f"while undoing the failed startup: {error}")
            self._forget_instances()
            raise

        self._state.initialized = True
        return module_instances

    async def shutdown(self, *, signal: str | None = None) -> None:
        """Run every teardown stage, then drop the instances the application built.

        ``signal`` names the signal that asked the process to stop and is passed on
        to the hooks that take one. No adapter supplies it yet, so it is always
        ``None`` until one does.
        """

        if not self._state.initialized:
            return

        errors = await self._tear_down(signal=signal)
        self._forget_instances()

        if errors:
            if len(errors) == 1:
                raise errors[0]
            raise LifecycleErrorGroup(
                f"{len(errors)} lifecycle hooks failed during shutdown", errors
            )

    async def _tear_down(self, *, signal: str | None) -> list[LifecycleError]:
        """Run all three teardown stages, returning every hook that failed.

        Every stage runs to completion even when hooks fail, so one buggy component
        cannot leak every other component's resources.
        """

        graph, container = self._module_graph, self._container
        module_instances = self._state.module_instances
        return [
            *await run_before_shutdown_hooks(graph, container, module_instances, signal),
            *await run_shutdown_hooks(graph, container, module_instances, signal),
            *await run_destroy_hooks(graph, container, module_instances),
        ]

    def _forget_instances(self) -> None:
        """Drop every instance the application built and reset the state to closed.

        Teardown has destroyed these instances, so keeping them cached would serve a
        destroyed provider to whoever resolves it next. Emptying the caches is also
        what makes startup repeatable: the next one builds an application from the
        same graph rather than resurrecting this one.
        """

        scope_manager = self._container.scope_manager
        scope_manager.singletons.clear()
        scope_manager.durable_instances.clear()
        scope_manager.clear_controller_singletons()
        self._state = LifecycleState(initialized=False, closed=True)
