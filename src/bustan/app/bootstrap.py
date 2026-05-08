"""Application bootstrap and runtime assembly."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..core.ioc.container import build_container
from ..core.lifecycle.manager import LifecycleManager
from ..core.module.dynamic import DynamicModule
from ..core.module.graph import build_module_graph
from ..platform.http.adapter import AbstractHttpAdapter, compile_adapter_routes
from ..platform.http.adapters.starlette_adapter import StarletteAdapter
from ..platform.http.compiler import compile_route_contracts
from ..platform.http.execution import compile_execution_plans
from ..pipeline.middleware import compile_middleware_registry
from .application import Application, ApplicationContext
from .lifespan import build_lifespan

if TYPE_CHECKING:
    from ..openapi import SwaggerOptions
    from ..platform.http.versioning import VersioningOptions
    from ..testing.overrides import PipelineOverrideRegistry


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
    lifecycle_manager = LifecycleManager(module_graph, container)

    # 2. Build lifecyle and routing configuration
    lifespan = None if _no_lifespan else build_lifespan(lifecycle_manager)
    route_contracts = compile_route_contracts(module_graph, container)
    execution_plans = compile_execution_plans(route_contracts)
    middleware_registry = compile_middleware_registry(module_graph)

    # 3. Instantiate the HTTP adapter with full configuration
    # (Starlette requires debug/lifespan at constructor time)
    http_adapter = adapter or StarletteAdapter(debug=debug, lifespan=lifespan)

    compiled_adapter_routes = compile_adapter_routes(
        http_adapter,
        route_contracts,
        container,
        execution_plans=execution_plans,
        pipeline_override_registry=pipeline_override_registry,
        versioning=versioning,
        middleware_registry=middleware_registry,
    )

    # 4. Register compiled routes through the adapter
    http_adapter.register_routes(list(compiled_adapter_routes))

    application = Application(
        http_adapter,
        container,
        lifecycle_manager,
        route_contracts=route_contracts,
        execution_plans=execution_plans,
    )
    _attach_runtime_artifacts(
        application,
        module_graph,
        container,
        route_contracts,
        execution_plans,
    )
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
    lifecycle_manager = LifecycleManager(module_graph, container)
    return ApplicationContext(container, lifecycle_manager)


def _attach_runtime_artifacts(
    application: Application,
    module_graph,
    container,
    route_contracts,
    execution_plans,
) -> None:
    server = application.get_http_server()
    state = getattr(server, "state", None)
    if state is None:
        return

    state.bustan_application = application
    state.bustan_container = container
    state.bustan_module_graph = module_graph
    state.bustan_route_contracts = route_contracts
    state.bustan_execution_plans = execution_plans
