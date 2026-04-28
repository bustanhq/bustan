"""Route compilation and Starlette router assembly."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from starlette.responses import JSONResponse
from starlette.routing import Router, Route

from ...core.ioc.container import Container
from ...core.errors import RouteDefinitionError
from ...core.module.graph import ModuleGraph
from ...core.ioc.tokens import APP_FILTER, APP_GUARD, APP_INTERCEPTOR, APP_PIPE
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
from .adapters.starlette import create_starlette_endpoint
from .versioning import VERSION_NEUTRAL, VersioningOptions, VersioningType, extract_request_version, normalize_versions

if TYPE_CHECKING:
    from ...testing.overrides import PipelineOverrideRegistry

EndpointHandler = Callable[[object], Awaitable[object]]


def build_router(
    module_graph: ModuleGraph,
    container: Container,
    *,
    pipeline_override_registry: PipelineOverrideRegistry | None = None,
    versioning: VersioningOptions | None = None,
) -> Router:
    """Build a Starlette router for the discovered application graph."""
    routes = compile_routes(
        module_graph,
        container,
        pipeline_override_registry=pipeline_override_registry,
        versioning=versioning,
    )
    return Router(routes=list(routes))


def compile_routes(
    module_graph: ModuleGraph,
    container: Container,
    *,
    pipeline_override_registry: PipelineOverrideRegistry | None = None,
    versioning: VersioningOptions | None = None,
) -> tuple[Route, ...]:
    """Compile controller metadata into Starlette Route objects."""

    seen_routes: dict[tuple[str, str], str] = {}
    compiled_routes: list[Route] = []
    versioned_dispatchers: dict[
        tuple[str, str], list[tuple[tuple[str, ...], EndpointHandler, str]]
    ] = defaultdict(list)
    global_pipeline = PipelineMetadata(
        guards=container.get_global_pipeline_providers(APP_GUARD),
        pipes=container.get_global_pipeline_providers(APP_PIPE),
        interceptors=container.get_global_pipeline_providers(APP_INTERCEPTOR),
        filters=container.get_global_pipeline_providers(APP_FILTER),
    )

    for node in module_graph.nodes:
        for controller_cls in node.controllers:
            controller_metadata = get_controller_metadata(controller_cls)
            assert controller_metadata is not None
            controller_pipeline = get_controller_pipeline_metadata(controller_cls, inherit=True)
            controller_versions = normalize_versions(controller_metadata.version)

            for route_definition in iter_controller_routes(controller_cls):
                binding_plan = compile_parameter_bindings(controller_cls, route_definition)
                pipeline_metadata = merge_pipeline_metadata(
                    global_pipeline,
                    controller_pipeline or PipelineMetadata(),
                    get_handler_pipeline_metadata(route_definition.handler) or PipelineMetadata(),
                )

                route_path = _join_paths(controller_metadata.prefix, route_definition.route.path)
                route_key = (route_definition.route.method, route_path)
                route_owner = f"{_qualname(controller_cls)}.{route_definition.handler_name}"
                route_versions = normalize_versions(route_definition.route.version)
                effective_versions = route_versions or controller_versions

                if versioning is None and route_key in seen_routes:
                    raise RouteDefinitionError(
                        f"Duplicate application route {route_definition.route.method} {route_path} "
                        f"declared by {seen_routes[route_key]} and {route_owner}"
                    )

                if versioning is None:
                    seen_routes[route_key] = route_owner

                endpoint = create_starlette_endpoint(
                    container,
                    node.key,
                    controller_cls,
                    route_definition,
                    binding_plan,
                    pipeline_metadata,
                    pipeline_override_registry,
                )

                if versioning is None:
                    compiled_routes.append(
                        Route(
                            path=route_path,
                            endpoint=endpoint,
                            methods=[route_definition.route.method],
                            name=route_owner,
                        )
                    )
                    continue

                if versioning.type is VersioningType.URI:
                    versioned_paths = _build_uri_paths(
                        route_path,
                        effective_versions,
                        versioning,
                    )
                    for versioned_path in versioned_paths:
                        versioned_key = (route_definition.route.method, versioned_path)
                        if versioned_key in seen_routes:
                            raise RouteDefinitionError(
                                f"Duplicate application route {route_definition.route.method} {versioned_path} "
                                f"declared by {seen_routes[versioned_key]} and {route_owner}"
                            )
                        seen_routes[versioned_key] = route_owner
                        compiled_routes.append(
                            Route(
                                path=versioned_path,
                                endpoint=endpoint,
                                methods=[route_definition.route.method],
                                name=route_owner,
                            )
                        )
                    continue

                existing = versioned_dispatchers[route_key]
                for existing_versions, _existing_endpoint, existing_owner in existing:
                    is_new_neutral = not effective_versions or VERSION_NEUTRAL in effective_versions
                    is_existing_neutral = not existing_versions or VERSION_NEUTRAL in existing_versions
                    if is_new_neutral and is_existing_neutral:
                        raise RouteDefinitionError(
                            f"Duplicate version-neutral route {route_definition.route.method} {route_path} "
                            f"declared by {existing_owner} and {route_owner}"
                        )
                    if is_new_neutral or is_existing_neutral:
                        continue
                    overlap = set(effective_versions) & set(existing_versions)
                    if overlap:
                        raise RouteDefinitionError(
                            f"Overlapping versions {sorted(overlap)} for route "
                            f"{route_definition.route.method} {route_path} "
                            f"declared by {existing_owner} and {route_owner}"
                        )
                existing.append(
                    (
                        effective_versions,
                        endpoint,
                        route_owner,
                    )
                )

    if versioning is not None and versioning.type in {
        VersioningType.HEADER,
        VersioningType.MEDIA_TYPE,
    }:
        for (method, path), handlers in versioned_dispatchers.items():
            compiled_routes.append(
                Route(
                    path=path,
                    endpoint=_build_version_dispatcher(
                        handlers,
                        versioning,
                    ),
                    methods=[method],
                    name=handlers[0][2],
                )
            )

    return tuple(compiled_routes)


def _build_uri_paths(
    route_path: str,
    versions: tuple[str, ...],
    options: VersioningOptions,
) -> tuple[str, ...]:
    if not versions or VERSION_NEUTRAL in versions:
        return (route_path,)

    versioned_paths: list[str] = []
    for version in versions:
        versioned_paths.append(_join_paths(f"/{options.prefix}{version}", route_path))
        if options.default_version == version:
            versioned_paths.append(route_path)
    return tuple(dict.fromkeys(versioned_paths))


def _build_version_dispatcher(
    handlers: list[tuple[tuple[str, ...], EndpointHandler, str]],
    options: VersioningOptions,
):
    async def endpoint(request):
        requested_version = extract_request_version(request, options)
        for versions, handler, _owner in handlers:
            if not versions or VERSION_NEUTRAL in versions:
                return await handler(request)
            if requested_version in versions:
                return await handler(request)
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    return endpoint
