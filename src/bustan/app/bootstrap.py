"""Application bootstrap and runtime assembly."""

from __future__ import annotations

from starlette.applications import Starlette

from ..core.module.graph import build_module_graph
from ..core.module.dynamic import DynamicModule
from ..core.ioc.container import build_container
from ..platform.http.routing import build_router
from .lifespan import build_lifespan
from .application import Application


def create_app(root_module: type[object] | DynamicModule) -> Application:
    """Create a fully assembled Bustan application from the root module."""
    module_graph = build_module_graph(root_module)
    container = build_container(module_graph)
    lifespan = build_lifespan(module_graph)
    router = build_router(module_graph, container)

    starlette_app = Starlette(
        debug=False,
        routes=router.routes,
        lifespan=lifespan,
    )

    return Application(starlette_app, container)


def bootstrap(root_module: type[object] | DynamicModule) -> Application:
    """Legacy alias for create_app."""
    return create_app(root_module)
