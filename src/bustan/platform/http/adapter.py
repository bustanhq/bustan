"""The adapter port, and the framework side of driving one.

The port itself is declared in ``bustan.contracts`` so that an adapter can be written
against it without importing framework code; it is re-exported here because this is
where the framework's own callers have always reached for it. What is defined here is
the framework's half: the construction contract that tells an adapter what the
framework decided before it existed, compiling the route plan, and refusing - before a
server starts - a route the chosen adapter cannot serve.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ...contracts import AbstractHttpAdapter, AdapterCapabilities, AdapterRoute
from .routing import CompiledAdapterRoute, compile_route_plan

if TYPE_CHECKING:
    from ...pipeline.middleware import MiddlewareRegistry
    from .compiler import RouteContract
    from .execution import ExecutionPlan

# What a server hands its lifespan: the server object itself, in exchange for a context
# manager held open for as long as that server serves. The argument is the transport's
# own object, so it is named only as ``object`` here; the framework writes to it through
# the handler it built, never through this alias.
type AdapterLifespan = Callable[[object], AbstractAsyncContextManager[None]]


@dataclass(frozen=True, slots=True)
class AdapterRuntime:
    """What the framework settled before an adapter existed, for the adapter to honour.

    Two things about a run are the framework's to decide and an adapter's to apply, and
    neither can be discovered from the port's methods. ``debug`` is how the deployment
    was started. ``lifespan`` is the handler that starts and stops the module graph, so
    an adapter that does not run it serves requests against modules whose ``on_startup``
    never fired.
    """

    debug: bool = False
    lifespan: AdapterLifespan | None = None


# An adapter the framework builds itself, rather than one it is handed already built.
# The framework calls it once, with the runtime, and serves through what comes back.
type AdapterFactory = Callable[[AdapterRuntime], AbstractHttpAdapter]


def build_http_adapter(
    adapter: AbstractHttpAdapter | AdapterFactory,
    runtime: AdapterRuntime,
) -> AbstractHttpAdapter:
    """Return the adapter to serve through, building it if it was supplied as a factory.

    An adapter passed as an instance is already constructed and is returned untouched:
    the framework cannot reach into a built object, so such an adapter carries whatever
    debug setting and lifespan its caller gave it. An adapter passed as a factory is
    called with *runtime* and therefore receives both, which is the only way a transport
    other than the one the framework builds by default can be given them.
    """

    if isinstance(adapter, AbstractHttpAdapter):
        return adapter

    built = adapter(runtime)
    if not isinstance(built, AbstractHttpAdapter):
        raise TypeError(
            f"An adapter factory must return an AbstractHttpAdapter, not {type(built).__name__}."
        )
    return built


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
    "AdapterFactory",
    "AdapterLifespan",
    "AdapterRoute",
    "AdapterRuntime",
    "CompiledAdapterRoute",
    "build_http_adapter",
    "compile_adapter_routes",
)
