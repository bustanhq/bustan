"""Application bootstrap helpers exposed by the public API."""

from starlette.applications import Starlette

from .container import build_container
from .lifecycle import build_lifespan
from .module_graph import build_module_graph
from .routing import compile_routes


def create_app(root_module: type[object]) -> Starlette:
    """Build a Starlette application from a decorated root module."""

    module_graph = build_module_graph(root_module)
    container = build_container(module_graph)
    routes = compile_routes(module_graph, container)

    application = Starlette(routes=list(routes), lifespan=build_lifespan(module_graph))
    # Expose bootstrap artifacts for tests, examples, and advanced integrations.
    application.state.bustan_container = container
    application.state.bustan_module_graph = module_graph
    application.state.bustan_root_module = root_module
    return application


def bootstrap(root_module: type[object]) -> Starlette:
    """Compatibility alias for create_app()."""

    return create_app(root_module)