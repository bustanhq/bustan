"""Route compilation and Starlette router assembly."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from starlette.routing import Router, Route

from ...core.ioc.container import Container
from ...core.errors import RouteDefinitionError
from ...core.module.graph import ModuleGraph
from ...core.utils import _join_paths, _qualname
from .abstractions import HttpResponse, to_starlette_response
from .compiler import RouteContract, compile_route_contracts
from .execution import ExecutionPlan, compile_execution_plans
from .adapters.starlette import create_starlette_endpoint
from .registry import RouteRegistry
from .versioning import VERSION_NEUTRAL, VersioningOptions, VersioningType, extract_request_version

if TYPE_CHECKING:
    from ...testing.overrides import PipelineOverrideRegistry
    from ...pipeline.middleware import MiddlewareRegistry

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
    middleware_registry: MiddlewareRegistry | None = None,
) -> tuple[Route, ...]:
    """Compile controller metadata into Starlette Route objects."""

    route_contracts = compile_route_contracts(module_graph, container)
    return compile_routes_from_contracts(
        route_contracts,
        container,
        pipeline_override_registry=pipeline_override_registry,
        versioning=versioning,
        middleware_registry=middleware_registry,
    )


def compile_routes_from_contracts(
    route_contracts: tuple[RouteContract, ...],
    container: Container,
    *,
    execution_plans: tuple[ExecutionPlan, ...] | None = None,
    pipeline_override_registry: PipelineOverrideRegistry | None = None,
    versioning: VersioningOptions | None = None,
    middleware_registry: MiddlewareRegistry | None = None,
) -> tuple[Route, ...]:
    """Compile route contracts into Starlette Route objects."""

    seen_routes: dict[tuple[str, str], str] = {}
    compiled_routes: list[Route] = []
    versioned_dispatchers: dict[
        tuple[str, str], list[tuple[tuple[str, ...], EndpointHandler, str, RouteContract, ExecutionPlan]]
    ] = defaultdict(list)
    if versioning is None:
        RouteRegistry(route_contracts).validate()
    _validate_starlette_route_support(route_contracts)

    if execution_plans is None:
        execution_plans = compile_execution_plans(route_contracts)

    for route_contract, execution_plan in zip(route_contracts, execution_plans, strict=True):
        controller_cls = route_contract.controller_cls
        route_definition = route_contract.route_definition
        route_path = route_contract.path
        route_key = (route_contract.method, route_path)
        route_owner = f"{_qualname(controller_cls)}.{route_contract.handler_name}"
        effective_versions = route_contract.versions

        if versioning is None and route_key in seen_routes:
            raise RouteDefinitionError(
                f"Duplicate application route {route_contract.method} {route_path} "
                f"declared by {seen_routes[route_key]} and {route_owner}"
            )

        if versioning is None:
            seen_routes[route_key] = route_owner

        endpoint = create_starlette_endpoint(
            container,
            execution_plan,
            middleware_registry.resolve_for(route_contract) if middleware_registry is not None else (),
            pipeline_override_registry,
        )

        if versioning is None:
            route = Route(
                path=route_path,
                endpoint=endpoint,
                methods=[route_definition.route.method],
                name=route_owner,
            )
            _attach_route_artifacts(route, endpoint, (route_contract,), (execution_plan,))
            compiled_routes.append(route)
            continue

        if versioning.type is VersioningType.URI:
            versioned_paths = _build_uri_paths(
                route_path,
                effective_versions,
                versioning,
            )
            for versioned_path in versioned_paths:
                versioned_key = (route_contract.method, versioned_path)
                if versioned_key in seen_routes:
                    raise RouteDefinitionError(
                        f"Duplicate application route {route_contract.method} {versioned_path} "
                        f"declared by {seen_routes[versioned_key]} and {route_owner}"
                    )
                seen_routes[versioned_key] = route_owner
                route = Route(
                    path=versioned_path,
                    endpoint=endpoint,
                    methods=[route_definition.route.method],
                    name=route_owner,
                )
                _attach_route_artifacts(route, endpoint, (route_contract,), (execution_plan,))
                compiled_routes.append(route)
            continue

        existing = versioned_dispatchers[route_key]
        for existing_versions, _existing_endpoint, existing_owner, _existing_contract, _existing_plan in existing:
            is_new_neutral = _is_neutral_version(effective_versions)
            is_existing_neutral = _is_neutral_version(existing_versions)
            if is_new_neutral and is_existing_neutral:
                raise RouteDefinitionError(
                    f"Duplicate version-neutral route {route_contract.method} {route_path} "
                    f"declared by {existing_owner} and {route_owner}"
                )
            if is_new_neutral or is_existing_neutral:
                continue
            overlap = set(effective_versions) & set(existing_versions)
            if overlap:
                raise RouteDefinitionError(
                    f"Overlapping versions {sorted(overlap)} for route "
                    f"{route_contract.method} {route_path} "
                    f"declared by {existing_owner} and {route_owner}"
                )
        existing.append(
            (
                effective_versions,
                endpoint,
                route_owner,
                route_contract,
                execution_plan,
            )
        )

    if versioning is not None and versioning.type in {
        VersioningType.HEADER,
        VersioningType.MEDIA_TYPE,
    }:
        for (method, path), handlers in versioned_dispatchers.items():
            endpoint = _build_version_dispatcher(
                handlers,
                versioning,
            )
            route = Route(
                path=path,
                endpoint=endpoint,
                methods=[method],
                name=handlers[0][2],
            )
            _attach_route_artifacts(
                route,
                endpoint,
                tuple(contract for _versions, _endpoint, _owner, contract, _plan in handlers),
                tuple(plan for _versions, _endpoint, _owner, _contract, plan in handlers),
            )
            compiled_routes.append(route)

    return tuple(compiled_routes)


def _attach_route_artifacts(
    route: Route,
    endpoint: EndpointHandler,
    contracts: tuple[RouteContract, ...],
    execution_plans: tuple[ExecutionPlan, ...],
) -> None:
    setattr(endpoint, "bustan_route_contracts", contracts)
    setattr(route, "bustan_route_contracts", contracts)
    setattr(endpoint, "bustan_execution_plans", execution_plans)
    setattr(route, "bustan_execution_plans", execution_plans)
    if len(contracts) == 1:
        setattr(endpoint, "bustan_route_contract", contracts[0])
        setattr(route, "bustan_route_contract", contracts[0])
    if len(execution_plans) == 1:
        setattr(endpoint, "bustan_execution_plan", execution_plans[0])
        setattr(route, "bustan_execution_plan", execution_plans[0])


def _is_neutral_version(versions: tuple[str, ...]) -> bool:
    """Return True when *versions* represents a version-neutral handler."""
    return not versions or VERSION_NEUTRAL in versions


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
    handlers: list[tuple[tuple[str, ...], EndpointHandler, str, RouteContract, ExecutionPlan]],
    options: VersioningOptions,
):
    async def endpoint(request):
        requested_version = extract_request_version(request, options)
        for versions, handler, _owner, _contract, _plan in handlers:
            if not versions or VERSION_NEUTRAL in versions:
                return await handler(request)
            if requested_version in versions:
                return await handler(request)
        return to_starlette_response(HttpResponse.json({"detail": "Not Found"}, status_code=404))

    return endpoint


def _validate_starlette_route_support(route_contracts: tuple[RouteContract, ...]) -> None:
    for route_contract in route_contracts:
        if route_contract.hosts:
            raise RouteDefinitionError(
                f"Direct Starlette route compilation does not support host routing for {route_contract.method} {route_contract.path}"
            )
