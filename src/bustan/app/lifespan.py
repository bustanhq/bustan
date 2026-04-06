"""Starlette lifespan integration for module lifecycle orchestration."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from starlette.applications import Starlette
from starlette.types import StatelessLifespan

from ..core.module.graph import ModuleGraph
from ..core.lifecycle.runner import run_lifecycle_stage, instantiate_lifecycle_modules


def build_lifespan(
    module_graph: ModuleGraph,
) -> StatelessLifespan[Starlette]:
    """Build the Starlette lifespan handler for the module graph."""

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        module_instances = instantiate_lifecycle_modules(module_graph.nodes)
        app.state.bustan_module_instances = module_instances

        await run_lifecycle_stage(module_graph.nodes, module_instances, "on_module_init")
        await run_lifecycle_stage(module_graph.nodes, module_instances, "on_app_startup")

        try:
            yield
        finally:
            await run_lifecycle_stage(
                tuple(reversed(module_graph.nodes)),
                module_instances,
                "on_app_shutdown",
            )
            await run_lifecycle_stage(
                tuple(reversed(module_graph.nodes)),
                module_instances,
                "on_module_destroy",
            )

    return lifespan
