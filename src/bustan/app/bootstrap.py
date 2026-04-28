"""Application bootstrap and runtime assembly."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..core.ioc.container import build_container
from ..core.module.dynamic import DynamicModule, ModuleKey
from ..core.module.graph import ModuleGraph
from ..core.module.graph import build_module_graph
from ..platform.http.adapter import AbstractHttpAdapter
from ..platform.http.adapters.starlette_adapter import StarletteAdapter
from ..platform.http.routing import build_router
from ..pipeline.middleware import ConditionalMiddleware, MiddlewareBinding, MiddlewareConsumer
from .application import Application, ApplicationContext
from .lifespan import build_lifespan

if TYPE_CHECKING:
    from ..openapi import SwaggerOptions
    from ..platform.http.versioning import VersioningOptions
    from ..testing.overrides import PipelineOverrideRegistry
    from ..core.ioc.container import Container


def create_app(
    root_module: type[object] | DynamicModule,
    *,
    debug: bool = False,
    adapter: AbstractHttpAdapter | None = None,
    pipeline_override_registry: PipelineOverrideRegistry | None = None,
    versioning: VersioningOptions | None = None,
    swagger: SwaggerOptions | None = None,
    _no_lifespan: bool = False,
) -> Application:
    """Create a fully assembled Bustan application from the root module."""
    # 1. Build application graph and DI container
    module_graph = build_module_graph(root_module)
    container = build_container(module_graph)

    # 2. Build lifecyle and routing configuration
    lifespan = None if _no_lifespan else build_lifespan(module_graph, container)
    router = build_router(
        module_graph,
        container,
        pipeline_override_registry=pipeline_override_registry,
        versioning=versioning,
    )

    # 3. Instantiate the HTTP adapter with full configuration
    # (Starlette requires debug/lifespan at constructor time)
    http_adapter = adapter or StarletteAdapter(debug=debug, lifespan=lifespan)

    # 4. Register compiled routes through the adapter
    http_adapter.register_routes(list(router.routes))

    # 5. Register module middleware after routes have been compiled.
    for module_key, middleware_binding in _collect_module_middleware(module_graph):
        for middleware in reversed(middleware_binding.middlewares):
            handler = _resolve_middleware(container, module_key, middleware)
            http_adapter.add_middleware(
                ConditionalMiddleware,
                handler=handler,
                include=tuple(middleware_binding.routes),
                exclude=tuple(middleware_binding.excluded),
            )

    application = Application(http_adapter, container)
    if swagger is not None:
        application.enable_swagger(
            swagger.path,
            swagger.document_builder.build(),
            swagger_ui_path=swagger.swagger_ui_path,
        )
    return application


def create_app_context(root_module: type[object] | DynamicModule) -> ApplicationContext:
    """Create a standalone application context for dependency injection."""
    module_graph = build_module_graph(root_module)
    container = build_container(module_graph)
    return ApplicationContext(container)


def _collect_module_middleware(
    module_graph: ModuleGraph,
) -> list[tuple[ModuleKey, MiddlewareBinding]]:
    collected: list[tuple[ModuleKey, MiddlewareBinding]] = []
    for node in module_graph.nodes:
        configure = getattr(node.module(), "configure", None)
        if not callable(configure):
            continue
        consumer = MiddlewareConsumer()
        configure(consumer)
        collected.extend((node.key, binding) for binding in consumer.bindings)
    return collected


def _resolve_middleware(container: Container, module_key: ModuleKey, middleware: object) -> Any:
    if isinstance(middleware, type):
        return container.instantiate_class(middleware, module=module_key)
    return middleware
