"""Compilation of controller routes into a transport-neutral route plan.

Nothing here knows which transport will serve the plan. Each entry names a path, the
methods it answers, what it needs from a transport, and one handler that takes the
neutral request contract and returns a neutral response; an adapter turns that into
whatever its own router registers.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ...contracts import AdapterRoute, HttpRequest, HttpResponse, RouteHandler
from ...core.errors import RouteDefinitionError
from ...core.ioc.container import Container
from ...core.module.graph import ModuleGraph
from ...core.utils import _join_paths, _qualname
from .compiler import ResponseStrategy, RouteContract, compile_route_contracts
from .execution import ExecutionPlan, compile_execution_plans, create_route_handler
from .params import ParameterSource
from .registry import RouteRegistry
from .versioning import VERSION_NEUTRAL, VersioningOptions, VersioningType, extract_request_version

if TYPE_CHECKING:
    from ...pipeline.middleware import MiddlewareRegistry
    from ...testing.overrides import PipelineOverrideRegistry

ROUTE_CONTRACT_ATTR = "bustan_route_contract"
ROUTE_CONTRACTS_ATTR = "bustan_route_contracts"
EXECUTION_PLAN_ATTR = "bustan_execution_plan"
EXECUTION_PLANS_ATTR = "bustan_execution_plans"


@dataclass(frozen=True, slots=True)
class CompiledAdapterRoute(AdapterRoute):
    """One planned route, with the compilation artifacts the framework kept beside it.

    An adapter reads only what :class:`AdapterRoute` declares. The contracts and
    execution plans are here for the framework's own tooling - route snapshots, the
    OpenAPI document, the routes command - which asks what produced a route.
    """

    contracts: tuple[RouteContract, ...] = ()
    execution_plans: tuple[ExecutionPlan, ...] = ()


def compile_routes(
    module_graph: ModuleGraph,
    container: Container,
    *,
    pipeline_override_registry: PipelineOverrideRegistry | None = None,
    versioning: VersioningOptions | None = None,
    middleware_registry: MiddlewareRegistry | None = None,
) -> tuple[CompiledAdapterRoute, ...]:
    """Compile every controller in the module graph into the neutral route plan."""

    route_contracts = compile_route_contracts(module_graph, container)
    return compile_route_plan(
        route_contracts,
        container,
        pipeline_override_registry=pipeline_override_registry,
        versioning=versioning,
        middleware_registry=middleware_registry,
    )


def compile_route_plan(
    route_contracts: tuple[RouteContract, ...],
    container: Container,
    *,
    execution_plans: tuple[ExecutionPlan, ...] | None = None,
    pipeline_override_registry: PipelineOverrideRegistry | None = None,
    versioning: VersioningOptions | None = None,
    middleware_registry: MiddlewareRegistry | None = None,
) -> tuple[CompiledAdapterRoute, ...]:
    """Compile route contracts into the neutral route plan an adapter registers.

    With no versioning configured, each contract becomes one entry and a repeated
    method and path is refused. URI versioning expands one contract into one entry per
    version; header and media type versioning collapse the versions of one method and
    path into a single entry that picks a handler by what the request asked for.
    """

    if versioning is None:
        RouteRegistry(route_contracts).validate()

    if execution_plans is None:
        execution_plans = compile_execution_plans(route_contracts)

    builder = _RoutePlanBuilder(
        container,
        versioning=versioning,
        middleware_registry=middleware_registry,
        pipeline_override_registry=pipeline_override_registry,
    )
    for route_contract, execution_plan in zip(route_contracts, execution_plans, strict=True):
        builder.add(route_contract, execution_plan)
    return builder.build()


@dataclass(frozen=True, slots=True)
class _VersionedHandler:
    """One version of a route that shares its method and path with other versions."""

    versions: tuple[str, ...]
    handler: RouteHandler
    owner: str
    contract: RouteContract
    execution_plan: ExecutionPlan


class _RoutePlanBuilder:
    """Accumulate compiled contracts into the route plan, refusing collisions."""

    def __init__(
        self,
        container: Container,
        *,
        versioning: VersioningOptions | None,
        middleware_registry: MiddlewareRegistry | None,
        pipeline_override_registry: PipelineOverrideRegistry | None,
    ) -> None:
        self._container = container
        self._versioning = versioning
        self._middleware_registry = middleware_registry
        self._pipeline_override_registry = pipeline_override_registry
        self._seen_routes: dict[tuple[str, str], str] = {}
        self._routes: list[CompiledAdapterRoute] = []
        self._versioned: dict[tuple[str, str], list[_VersionedHandler]] = defaultdict(list)

    def add(self, route_contract: RouteContract, execution_plan: ExecutionPlan) -> None:
        """Plan one compiled contract, or hold it for a version dispatcher."""

        owner = f"{_qualname(route_contract.controller_cls)}.{route_contract.handler_name}"
        handler = create_route_handler(
            self._container,
            execution_plan,
            self._middleware_registry.resolve_for(route_contract)
            if self._middleware_registry is not None
            else (),
            self._pipeline_override_registry,
        )

        if self._versioning is None:
            self._claim((route_contract.method, route_contract.path), owner)
            self._append(route_contract.path, owner, handler, (route_contract,), (execution_plan,))
            return

        if self._versioning.type is VersioningType.URI:
            for path in _build_uri_paths(
                route_contract.path, route_contract.versions, self._versioning
            ):
                self._claim((route_contract.method, path), owner)
                self._append(path, owner, handler, (route_contract,), (execution_plan,))
            return

        route_key = (route_contract.method, route_contract.path)
        self._check_version_overlap(route_key, route_contract, owner)
        self._versioned[route_key].append(
            _VersionedHandler(
                versions=route_contract.versions,
                handler=handler,
                owner=owner,
                contract=route_contract,
                execution_plan=execution_plan,
            )
        )

    def build(self) -> tuple[CompiledAdapterRoute, ...]:
        """Return the plan, adding one dispatching entry per versioned method and path."""

        versioning = self._versioning
        if versioning is not None and versioning.type in {
            VersioningType.HEADER,
            VersioningType.MEDIA_TYPE,
        }:
            for (_method, path), handlers in self._versioned.items():
                self._append(
                    path,
                    handlers[0].owner,
                    _build_version_dispatcher(tuple(handlers), versioning),
                    tuple(handler.contract for handler in handlers),
                    tuple(handler.execution_plan for handler in handlers),
                )
        return tuple(self._routes)

    def _claim(self, route_key: tuple[str, str], owner: str) -> None:
        existing = self._seen_routes.get(route_key)
        if existing is not None:
            method, path = route_key
            raise RouteDefinitionError(
                f"Duplicate application route {method} {path} declared by {existing} and {owner}"
            )
        self._seen_routes[route_key] = owner

    def _check_version_overlap(
        self, route_key: tuple[str, str], route_contract: RouteContract, owner: str
    ) -> None:
        method, path = route_key
        is_new_neutral = _is_neutral_version(route_contract.versions)
        for existing in self._versioned[route_key]:
            is_existing_neutral = _is_neutral_version(existing.versions)
            if is_new_neutral and is_existing_neutral:
                raise RouteDefinitionError(
                    f"Duplicate version-neutral route {method} {path} "
                    f"declared by {existing.owner} and {owner}"
                )
            if is_new_neutral or is_existing_neutral:
                continue
            overlap = set(route_contract.versions) & set(existing.versions)
            if overlap:
                raise RouteDefinitionError(
                    f"Overlapping versions {sorted(overlap)} for route {method} {path} "
                    f"declared by {existing.owner} and {owner}"
                )

    def _append(
        self,
        path: str,
        owner: str,
        handler: RouteHandler,
        contracts: tuple[RouteContract, ...],
        execution_plans: tuple[ExecutionPlan, ...],
    ) -> None:
        first = contracts[0]
        self._routes.append(
            CompiledAdapterRoute(
                path=path,
                methods=tuple(dict.fromkeys(contract.method for contract in contracts)),
                name=owner,
                handler=handler,
                hosts=first.hosts,
                requires_raw_body=any(_requires_raw_body(contract) for contract in contracts),
                requires_streaming=any(_requires_streaming(contract) for contract in contracts),
                attributes=_route_attributes(contracts, execution_plans),
                contracts=contracts,
                execution_plans=execution_plans,
            )
        )


def _route_attributes(
    contracts: tuple[RouteContract, ...],
    execution_plans: tuple[ExecutionPlan, ...],
) -> tuple[tuple[str, object], ...]:
    """Name what the adapter leaves on the registration it builds for a route.

    Route introspection reads a running server's routes and asks what compiled each
    one, so the compiled artifacts travel with the registration. The singular names
    are set only where a route has exactly one of each, which is every route that is
    not a version dispatcher.
    """

    attributes: list[tuple[str, object]] = [
        (ROUTE_CONTRACTS_ATTR, contracts),
        (EXECUTION_PLANS_ATTR, execution_plans),
    ]
    if len(contracts) == 1:
        attributes.append((ROUTE_CONTRACT_ATTR, contracts[0]))
    if len(execution_plans) == 1:
        attributes.append((EXECUTION_PLAN_ATTR, execution_plans[0]))
    return tuple(attributes)


def _requires_raw_body(route_contract: RouteContract) -> bool:
    """Return whether serving this route means reading the request body."""

    return any(
        binding.source
        in {
            ParameterSource.BODY,
            ParameterSource.FILE,
            ParameterSource.FILES,
            ParameterSource.INFERRED,
        }
        for binding in route_contract.binding_plan.parameters
    )


def _requires_streaming(route_contract: RouteContract) -> bool:
    """Return whether serving this route means writing a response in chunks."""

    return route_contract.response_plan.strategy is ResponseStrategy.STREAM


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
    handlers: tuple[_VersionedHandler, ...],
    options: VersioningOptions,
) -> RouteHandler:
    """Pick the handler whose versions match what the request asked for."""

    async def dispatch(request: HttpRequest) -> object:
        requested_version = extract_request_version(request, options)
        for entry in handlers:
            if _is_neutral_version(entry.versions) or requested_version in entry.versions:
                return await entry.handler(request)
        return HttpResponse.json({"detail": "Not Found"}, status_code=404)

    return dispatch


__all__ = (
    "CompiledAdapterRoute",
    "EXECUTION_PLANS_ATTR",
    "EXECUTION_PLAN_ATTR",
    "ROUTE_CONTRACTS_ATTR",
    "ROUTE_CONTRACT_ATTR",
    "compile_route_plan",
    "compile_routes",
)
