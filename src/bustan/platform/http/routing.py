"""Route compilation and Starlette router assembly."""

from __future__ import annotations

from starlette.routing import Router, Route

from ...core.ioc.container import Container
from ...core.errors import RouteDefinitionError
from ...core.module.graph import ModuleGraph
from ...core.utils import _join_paths, _qualname
from .metadata import (
    get_controller_metadata,
    iter_controller_routes,
)
from ...pipeline.metadata import (
    PipelineMetadata,
    get_controller_pipeline_metadata,
    get_handler_pipeline_metadata,
    merge_pipeline_metadata,
)
from .params import compile_parameter_bindings
from .controller_factory import ControllerFactory
from .adapters.starlette import create_starlette_endpoint


def build_router(module_graph: ModuleGraph, container: Container) -> Router:
    """Build a Starlette router for the discovered application graph."""
    routes = compile_routes(module_graph, container)
    return Router(routes=list(routes))


def compile_routes(module_graph: ModuleGraph, container: Container) -> tuple[Route, ...]:
    """Compile controller metadata into Starlette Route objects."""

    seen_routes: dict[tuple[str, str], str] = {}
    compiled_routes: list[Route] = []
    _factory = ControllerFactory(container)

    for node in module_graph.nodes:
        for controller_cls in node.controllers:
            controller_metadata = get_controller_metadata(controller_cls)
            assert controller_metadata is not None
            controller_pipeline = get_controller_pipeline_metadata(controller_cls, inherit=True)

            for route_definition in iter_controller_routes(controller_cls):
                binding_plan = compile_parameter_bindings(controller_cls, route_definition)
                pipeline_metadata = merge_pipeline_metadata(
                    controller_pipeline or PipelineMetadata(),
                    get_handler_pipeline_metadata(route_definition.handler) or PipelineMetadata(),
                )

                route_path = _join_paths(controller_metadata.prefix, route_definition.route.path)
                route_key = (route_definition.route.method, route_path)
                route_owner = f"{_qualname(controller_cls)}.{route_definition.handler_name}"

                if route_key in seen_routes:
                    raise RouteDefinitionError(
                        f"Duplicate application route {route_definition.route.method} {route_path} "
                        f"declared by {seen_routes[route_key]} and {route_owner}"
                    )

                seen_routes[route_key] = route_owner

                compiled_routes.append(
                    Route(
                        path=route_path,
                        endpoint=create_starlette_endpoint(
                            container,
                            node.key,
                            controller_cls,
                            route_definition,
                            binding_plan,
                            pipeline_metadata,
                        ),
                        methods=[route_definition.route.method],
                        name=route_owner,
                    )
                )

    return tuple(compiled_routes)
