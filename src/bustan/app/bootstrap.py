"""Application bootstrap and runtime assembly."""

from __future__ import annotations

from ..core.ioc.container import build_container
from ..core.module.dynamic import DynamicModule
from ..core.module.graph import build_module_graph
from ..platform.http.adapter import AbstractHttpAdapter
from ..platform.http.adapters.starlette_adapter import StarletteAdapter
from ..platform.http.routing import build_router
from .application import Application, ApplicationContext
from .lifespan import build_lifespan


def create_app(
    root_module: type[object] | DynamicModule,
    *,
    debug: bool = False,
    adapter: AbstractHttpAdapter | None = None,
) -> Application:
    """Create a fully assembled Bustan application from the root module."""
    # 1. Build application graph and DI container
    module_graph = build_module_graph(root_module)
    container = build_container(module_graph)

    # 2. Build lifecyle and routing configuration
    lifespan = build_lifespan(module_graph)
    router = build_router(module_graph, container)

    # 3. Instantiate the HTTP adapter with full configuration
    # (Starlette requires debug/lifespan at constructor time)
    http_adapter = adapter or StarletteAdapter(debug=debug, lifespan=lifespan)

    # 4. Register compiled routes through the adapter
    http_adapter.register_routes(list(router.routes))

    return Application(http_adapter, container)


def create_app_context(root_module: type[object] | DynamicModule) -> ApplicationContext:
    """Create a standalone application context for dependency injection."""
    module_graph = build_module_graph(root_module)
    container = build_container(module_graph)
    return ApplicationContext(container)
