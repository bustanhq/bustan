"""Starlette lifespan integration for module lifecycle orchestration."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from starlette.applications import Starlette
from starlette.types import StatelessLifespan

from ..core.ioc.container import Container
from ..core.module.graph import ModuleGraph
from ..core.lifecycle.runner import (
    run_bootstrap_hooks,
    run_destroy_hooks,
    run_init_hooks,
    run_shutdown_hooks,
)


def build_lifespan(
    module_graph: ModuleGraph,
    container: Container,
) -> StatelessLifespan[Starlette]:
    """Build the Starlette lifespan handler for the module graph."""

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        module_instances = await run_init_hooks(module_graph, container)
        app.state.bustan_module_instances = module_instances

        await run_bootstrap_hooks(module_graph, container, module_instances)

        try:
            yield
        finally:
            await run_shutdown_hooks(module_graph, container, module_instances)
            await run_destroy_hooks(module_graph, container, module_instances)

    return lifespan
