"""Starlette lifespan integration for module lifecycle orchestration."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from starlette.applications import Starlette
from starlette.types import StatelessLifespan

from ..core.lifecycle.manager import LifecycleManager


def build_lifespan(lifecycle_manager: LifecycleManager) -> StatelessLifespan[Starlette]:
    """Build the Starlette lifespan handler for the module graph."""

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        module_instances = await lifecycle_manager.startup()
        app.state.bustan_module_instances = module_instances

        try:
            yield
        finally:
            await lifecycle_manager.shutdown()

    return lifespan
