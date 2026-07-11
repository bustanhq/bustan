"""Starlette adapter compiler for compiled route contracts."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ....core.ioc.container import Container
from ..adapter import CompiledAdapterRoute
from ..routing import compile_routes_from_contracts

if TYPE_CHECKING:
    from ..compiler import RouteContract
    from ..execution import ExecutionPlan
    from ....pipeline.middleware import MiddlewareRegistry


class StarletteAdapterCompiler:
    """Compile route contracts into Starlette registration objects."""

    def __init__(
        self,
        container: Container,
        *,
        pipeline_override_registry=None,
        versioning=None,
        middleware_registry: MiddlewareRegistry | None = None,
    ) -> None:
        self._container = container
        self._pipeline_override_registry = pipeline_override_registry
        self._versioning = versioning
        self._middleware_registry = middleware_registry

    def compile(
        self,
        route_contracts: tuple[RouteContract, ...],
        execution_plans: tuple[ExecutionPlan, ...] | None = None,
    ) -> tuple[CompiledAdapterRoute, ...]:
        routes = compile_routes_from_contracts(
            route_contracts,
            self._container,
            execution_plans=execution_plans,
            pipeline_override_registry=self._pipeline_override_registry,
            versioning=self._versioning,
            middleware_registry=self._middleware_registry,
        )
        return tuple(
            CompiledAdapterRoute(
                registration=route,
                contracts=getattr(route, "bustan_route_contracts", ()),
                execution_plans=getattr(route, "bustan_execution_plans", ()),
                path=route.path,
                methods=_compiled_methods(getattr(route, "bustan_route_contracts", ()), route.methods),
                name=route.name,
            )
            for route in routes
        )


def _compiled_methods(
    contracts: tuple[RouteContract, ...], route_methods: set[str] | None
) -> tuple[str, ...]:
    if contracts:
        return tuple(dict.fromkeys(getattr(contract, "method") for contract in contracts))
    return tuple(route_methods or ())