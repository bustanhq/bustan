"""Shared application lifecycle orchestration."""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import cast

from ...common.types import ProviderScope
from ..errors import LifecycleError
from ..ioc.container import Container
from ..module.dynamic import ModuleKey
from ..module.graph import ModuleGraph
from .runner import (
    run_before_shutdown_hooks,
    run_bootstrap_hooks,
    run_destroy_hooks,
    run_init_hooks,
    run_shutdown_hooks,
)


@dataclass(slots=True)
class LifecycleState:
    """Mutable lifecycle state owned by one application context."""

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
        if self._state.closed:
            raise LifecycleError("Application lifecycle is already closed")
        if self._state.initialized:
            return self._state.module_instances

        await self._warm_async_factories()
        module_instances = await run_init_hooks(self._module_graph, self._container)
        await run_bootstrap_hooks(self._module_graph, self._container, module_instances)
        self._state = LifecycleState(
            initialized=True,
            closed=False,
            module_instances=module_instances,
        )
        return module_instances

    async def shutdown(self, *, signal: str | None = None) -> None:
        if not self._state.initialized or self._state.closed:
            return

        await run_before_shutdown_hooks(
            self._module_graph,
            self._container,
            self._state.module_instances,
            signal,
        )
        await run_shutdown_hooks(
            self._module_graph,
            self._container,
            self._state.module_instances,
            signal,
        )
        await run_destroy_hooks(
            self._module_graph,
            self._container,
            self._state.module_instances,
        )
        self._state.closed = True

    async def _warm_async_factories(self) -> None:
        for node in reversed(self._module_graph.nodes):
            for binding in node.bindings:
                if binding.scope is not ProviderScope.SINGLETON:
                    continue
                if binding.resolver_kind != "factory":
                    continue
                factory, _inject_tokens = cast(tuple[object, tuple[object, ...]], binding.target)
                if not inspect.iscoroutinefunction(factory):
                    continue
                await self._container.resolve_async(binding.token, module=node.key)
