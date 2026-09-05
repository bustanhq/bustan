"""Server lifespan integration for module lifecycle orchestration."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any

from ..core.lifecycle.manager import LifecycleManager

# What a server hands its lifespan: the server object itself, in exchange for a
# context manager held open for as long as that server serves. The argument is typed
# loosely because it is the transport's own object and the framework only writes the
# started module instances onto it.
type ServerLifespan = Callable[[Any], AbstractAsyncContextManager[None]]


def build_lifespan(lifecycle_manager: LifecycleManager) -> ServerLifespan:
    """Build the lifespan handler that starts and stops the module graph."""

    @asynccontextmanager
    async def lifespan(app: Any) -> AsyncIterator[None]:
        # Startup is inside the guard: a startup that fails part-way has resources
        # to release, and one that fails outside a ``try`` releases none of them.
        try:
            module_instances = await lifecycle_manager.startup()
            app.state.bustan_module_instances = module_instances
            yield
        finally:
            await lifecycle_manager.shutdown()

    return lifespan
