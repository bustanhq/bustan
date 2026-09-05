"""The adapter port, and the framework side of driving one.

The port itself is declared in ``bustan.contracts`` so that an adapter can be written
against it without importing framework code; it is re-exported here because this is
where the framework's own callers have always reached for it. What is defined here is
the framework's half: compiling the route plan and refusing, before a server starts, a
route the chosen adapter cannot serve.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...contracts import AbstractHttpAdapter, AdapterCapabilities, AdapterRoute
from .routing import CompiledAdapterRoute, compile_route_plan

if TYPE_CHECKING:
    from ...pipeline.middleware import MiddlewareRegistry
    from .compiler import RouteContract
    from .execution import ExecutionPlan


def compile_adapter_routes(
    adapter: AbstractHttpAdapter,
    route_contracts: tuple[RouteContract, ...],
    container: Any,
    *,
    execution_plans: tuple[ExecutionPlan, ...] | None = None,
    pipeline_override_registry: Any | None = None,
    versioning: Any | None = None,
    middleware_registry: MiddlewareRegistry | None = None,
) -> tuple[CompiledAdapterRoute, ...]:
    """Compile route contracts into the plan *adapter* will be asked to register.

    The plan is the framework's work and does not depend on which adapter was chosen;
    the adapter is consulted only to reject a route needing a capability it lacks,
    which happens here rather than at the first request that would have needed it.
    """

    route_plan = compile_route_plan(
        route_contracts,
        container,
        execution_plans=execution_plans,
        pipeline_override_registry=pipeline_override_registry,
        versioning=versioning,
        middleware_registry=middleware_registry,
    )
    _validate_adapter_capabilities(adapter, route_plan)
    return route_plan


def _validate_adapter_capabilities(
    adapter: AbstractHttpAdapter,
    route_plan: tuple[CompiledAdapterRoute, ...],
) -> None:
    from ...core.errors import RouteDefinitionError

    capabilities = getattr(adapter, "capabilities", AdapterCapabilities())

    for route in route_plan:
        methods = "/".join(route.methods)

        if route.hosts and not capabilities.supports_host_routing:
            raise RouteDefinitionError(
                f"{type(adapter).__name__} does not support host routing for {methods} {route.path}"
            )

        if route.requires_raw_body and not capabilities.supports_raw_body:
            raise RouteDefinitionError(
                f"{type(adapter).__name__} does not support raw body access required by "
                f"{methods} {route.path}"
            )

        if route.requires_streaming and not capabilities.supports_streaming_responses:
            raise RouteDefinitionError(
                f"{type(adapter).__name__} does not support streaming responses required by "
                f"{methods} {route.path}"
            )


__all__ = (
    "AbstractHttpAdapter",
    "AdapterCapabilities",
    "AdapterRoute",
    "CompiledAdapterRoute",
    "compile_adapter_routes",
)
