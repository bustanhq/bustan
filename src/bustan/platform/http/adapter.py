"""Abstract base class for HTTP framework adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from .compiler import RouteContract
    from .execution import ExecutionPlan
    from ...pipeline.middleware import MiddlewareRegistry


@dataclass(frozen=True, slots=True)
class CompiledAdapterRoute:
    """Concrete adapter registration produced from compiled route contracts."""

    registration: object
    contracts: tuple[RouteContract, ...]
    path: str
    methods: tuple[str, ...]
    name: str | None = None
    execution_plans: tuple[ExecutionPlan, ...] = ()


@dataclass(frozen=True, slots=True)
class AdapterCapabilities:
    """Explicit capabilities supported by one HTTP adapter."""

    supports_host_routing: bool = False
    supports_raw_body: bool = False
    supports_streaming_responses: bool = True
    supports_websocket_upgrade: bool = False


class AbstractHttpAdapter(ABC):
    """Base class for decoupling Bustan from specific web frameworks.

    Adapters are responsible for wrapping the underlying framework instance
    (e.g., Starlette, FastAPI) and handling route registration and 
    server initialization.
    """

    name: str
    capabilities: AdapterCapabilities

    @abstractmethod
    def get_instance(self) -> Any:
        """Return the underlying framework instance (e.g., Starlette App)."""
        pass

    @abstractmethod
    def register_routes(self, routes: list[CompiledAdapterRoute]) -> None:
        """Register compiled routes into the underlying engine."""
        pass

    @abstractmethod
    def add_middleware(self, middleware_class: type, **options: Any) -> None:
        """Register a framework middleware around the underlying engine."""
        pass

    @abstractmethod
    async def listen(
        self, 
        port: int, 
        host: str = "127.0.0.1", 
        reload: bool = False, 
        **kwargs: Any
    ) -> None:
        """Start the ASGI server asynchronously."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Shutdown the underlying server/engine."""
        pass

    @abstractmethod
    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        """All Bustan HTTP adapters must be valid ASGI callables."""
        pass


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
    """Compile route contracts into adapter registrations."""

    _validate_adapter_capabilities(adapter, route_contracts)

    from .adapters.starlette_adapter import StarletteAdapter
    from .adapters.starlette_compiler import StarletteAdapterCompiler

    if isinstance(adapter, StarletteAdapter):
        return StarletteAdapterCompiler(
            container,
            pipeline_override_registry=pipeline_override_registry,
            versioning=versioning,
            middleware_registry=middleware_registry,
        ).compile(route_contracts, execution_plans)

    raise TypeError(f"Unsupported HTTP adapter: {type(adapter).__name__}")


def _validate_adapter_capabilities(
    adapter: AbstractHttpAdapter,
    route_contracts: tuple[RouteContract, ...],
) -> None:
    from ...core.errors import RouteDefinitionError

    capabilities = getattr(adapter, "capabilities", AdapterCapabilities())

    for route_contract in route_contracts:
        if getattr(route_contract, "hosts", ()) and not capabilities.supports_host_routing:
            raise RouteDefinitionError(
                f"{type(adapter).__name__} does not support host routing for {route_contract.method} {route_contract.path}"
            )

        if not capabilities.supports_raw_body and _requires_raw_body(route_contract):
            raise RouteDefinitionError(
                f"{type(adapter).__name__} does not support raw body access required by {route_contract.method} {route_contract.path}"
            )

        if not capabilities.supports_streaming_responses and _requires_streaming(route_contract):
            raise RouteDefinitionError(
                f"{type(adapter).__name__} does not support streaming responses required by {route_contract.method} {route_contract.path}"
            )


def _requires_raw_body(route_contract: RouteContract) -> bool:
    from .params import ParameterSource

    binding_plan = getattr(route_contract, "binding_plan")
    for binding in binding_plan.parameters:
        if binding.source in {
            ParameterSource.BODY,
            ParameterSource.FILE,
            ParameterSource.FILES,
            ParameterSource.INFERRED,
        }:
            return True
    return False


def _requires_streaming(route_contract: RouteContract) -> bool:
    from .compiler import ResponseStrategy

    return route_contract.response_plan.strategy is ResponseStrategy.STREAM


__all__ = (
    "AbstractHttpAdapter",
    "AdapterCapabilities",
    "CompiledAdapterRoute",
    "compile_adapter_routes",
)
