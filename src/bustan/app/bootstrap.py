"""Application bootstrap and runtime assembly."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..kernel.ioc.container import build_container
from ..kernel.lifecycle.manager import LifecycleManager
from ..kernel.module.dynamic import DynamicModule
from ..kernel.module.graph import build_module_graph
from ..pipeline.middleware import compile_middleware_registry
from ..runtime.adapter import (
    AbstractHttpAdapter,
    AdapterFactory,
    AdapterRuntime,
    build_http_adapter,
    compile_adapter_routes,
)
from ..runtime.compiler import compile_route_contracts
from ..runtime.execution import compile_execution_plans
from .application import Application, ApplicationContext
from .lifespan import build_lifespan

if TYPE_CHECKING:
    from ..kernel.ioc.container import Container
    from ..openapi import SwaggerOptions
    from ..runtime.versioning import VersioningOptions
    from ..testing.overrides import PipelineOverrideRegistry


def create_app(
    root_module: type[object] | DynamicModule,
    *,
    debug: bool = False,
    adapter: AbstractHttpAdapter | AdapterFactory | None = None,
    pipeline_override_registry: PipelineOverrideRegistry | None = None,
    versioning: VersioningOptions | None = None,
    swagger: SwaggerOptions | None = None,
) -> Application:
    """Create a fully assembled Bustan application from the root module.

    ``adapter`` chooses the transport. Left out, the application serves through the
    Starlette adapter, which needs the ``starlette`` extra installed. Given a built
    adapter, that adapter serves as it stands. Given a callable, the framework calls it
    with an :class:`AdapterRuntime` and serves through what it returns, which is how an
    adapter other than the default is handed ``debug`` and the lifespan that starts and
    stops the module graph.
    """
    return _create_app(
        root_module,
        debug=debug,
        adapter=adapter,
        pipeline_override_registry=pipeline_override_registry,
        versioning=versioning,
        swagger=swagger,
        no_lifespan=False,
    )


def _create_app(
    root_module: type[object] | DynamicModule,
    *,
    debug: bool = False,
    adapter: AbstractHttpAdapter | AdapterFactory | None = None,
    pipeline_override_registry: PipelineOverrideRegistry | None = None,
    versioning: VersioningOptions | None = None,
    swagger: SwaggerOptions | None = None,
    no_lifespan: bool = False,
) -> Application:
    """Internal application factory used for alternate lifecycle wiring."""
    # 1. Build application graph and DI container
    module_graph = build_module_graph(root_module)
    container = build_container(module_graph)
    lifecycle_manager = LifecycleManager(module_graph, container)

    # The context is seated before anything is compiled, because compilation resolves
    # providers and a provider that injects APPLICATION must be answered the same way
    # here as it is on the request that reaches it later.
    application_context = _seat_application_context(container, lifecycle_manager)

    # 2. Build lifecyle and routing configuration
    lifespan = None if no_lifespan else build_lifespan(lifecycle_manager)
    route_contracts = compile_route_contracts(module_graph, container)
    execution_plans = compile_execution_plans(route_contracts)
    middleware_registry = compile_middleware_registry(module_graph)

    # 3. Instantiate the HTTP adapter with full configuration
    adapter_runtime = AdapterRuntime(debug=debug, lifespan=lifespan)
    http_adapter = build_http_adapter(adapter or _default_adapter, adapter_runtime)

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
    # The context and the application it serves HTTP through name each other, so what
    # a provider is injected with can still report the routes the application compiled.
    # The assembler is the only writer; everything else reads the context's accessor.
    application_context._http_application = application
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


_STARLETTE_EXTRA_REQUIREMENT = (
    "Bustan serves HTTP through a transport adapter, and the adapter it uses by default "
    "is built on Starlette, which is not installed.\n\n"
    "Install it with:\n\n"
    "    pip install 'bustan[starlette]'\n\n"
    "or pass an adapter of your own as create_app(..., adapter=...)."
)


def _default_adapter(runtime: AdapterRuntime) -> AbstractHttpAdapter:
    """Build the adapter an application gets when it names none.

    The import is deferred so that importing ``bustan`` never imports a web server: an
    application that brings its own adapter, and every use of the framework that serves
    no HTTP at all, needs neither Starlette nor the extra that installs it.
    """

    try:
        from ..adapters.starlette import StarletteAdapter
    except ModuleNotFoundError as error:
        # Only the absent extra is turned into advice. Anything else missing underneath
        # the adapter is a real import failure, and hiding it behind an install
        # instruction would send the reader to fix the one thing that is not wrong.
        if error.name not in {"starlette", "uvicorn"}:
            raise
        raise ImportError(_STARLETTE_EXTRA_REQUIREMENT) from error

    return StarletteAdapter(debug=runtime.debug, lifespan=runtime.lifespan)


def create_app_context(root_module: type[object] | DynamicModule) -> ApplicationContext:
    """Create a standalone application context for dependency injection."""
    module_graph = build_module_graph(root_module)
    container = build_container(module_graph)
    lifecycle_manager = LifecycleManager(module_graph, container)
    return _seat_application_context(container, lifecycle_manager)


def _seat_application_context(
    container: Container, lifecycle_manager: LifecycleManager
) -> ApplicationContext:
    """Build the application context a container is resolved against, and seat it.

    One context is built per container, whether or not the application it belongs to
    also serves HTTP, and the container is told about it here. That is what makes
    `APPLICATION` one type: every entry point into the container - the application
    itself, a request being served, an imperative resolution - answers with this
    object rather than with whatever the caller happened to arrive holding.
    """

    context = ApplicationContext(container, lifecycle_manager)
    container.kernel.belongs_to(context)
    return context


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
