"""Server lifespan integration for module lifecycle orchestration."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any

from ..kernel.lifecycle.manager import LifecycleManager
from .application import entered_application_scope, owning_application

# What a server hands its lifespan: the server object itself, in exchange for a
# context manager held open for as long as that server serves. The argument is typed
# loosely because it is the transport's own object and the framework only writes the
# started module instances onto it.
type ServerLifespan = Callable[[Any], AbstractAsyncContextManager[None]]


def build_lifespan(lifecycle_manager: LifecycleManager) -> ServerLifespan:
    """Build the lifespan handler that starts and stops the module graph."""

    @asynccontextmanager
    async def lifespan(app: Any) -> AsyncIterator[None]:
        # The application is the running application for the whole of startup and for
        # the whole of teardown, the same way it is when a caller drives the same graph
        # itself, so a provider built eagerly by a server may inject the application
        # exactly as one built eagerly by a caller can.
        application = owning_application(lifecycle_manager)
        # Startup is inside the guard: a startup that fails part-way has resources
        # to release, and one that fails outside a ``try`` releases none of them.
        try:
            # Each stage holds the scope on its own rather than one scope spanning the
            # suspension below, because a server may enter and leave a lifespan from
            # two different tasks and a binding released in another task is not
            # released at all.
            with entered_application_scope(application):
                module_instances = await lifecycle_manager.startup()
            app.state.bustan_module_instances = module_instances
            yield
        finally:
            with entered_application_scope(application):
                await lifecycle_manager.shutdown()

    return lifespan
