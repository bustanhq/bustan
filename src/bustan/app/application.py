"""Public application wrapper and context for the Bustan framework."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from ..core.ioc.container import Container
    from ..core.lifecycle.manager import LifecycleManager
    from ..core.module.graph import ModuleGraph
    from ..platform.http.adapter import AbstractHttpAdapter
    from ..platform.http.compiler import RouteContract
    from ..platform.http.execution import ExecutionPlan
    from ..security.cors import CorsOptions


class ApplicationContext:
    """A standalone application context for dependency injection.

    This provides a clean interface for resolving services from the Bustan
    IoC container, without an associated HTTP server instance.
    """

    def __init__(
        self,
        container: Container,
        lifecycle_manager: LifecycleManager | None = None,
    ) -> None:
        self._container = container
        self._lifecycle_manager = lifecycle_manager

    @property
    def container(self) -> Container:
        """Accessor for the underlying dependency injection container."""
        return self._container

    @property
    def module_graph(self) -> ModuleGraph:
        """Accessor for the discovered module graph."""
        return self._container.module_graph

    @property
    def root_module(self) -> Any:
        """Accessor for the application's root module class."""
        return self._container.module_graph.root_module

    @property
    def root_key(self) -> Any:
        """Accessor for the application's root module key (ModuleKey)."""
        return self._container.module_graph.root_key

    def get(self, token: object) -> Any:
        """Resolve a provider from the root module context.

        This is a non-request-scoped resolution. For request-scoped
        providers, use the dependency injection system directly via
        decorators (@Param, @Body, etc.) or app.resolve().
        """
        application_token = self._container.scope_manager.push_application(self)
        try:
            return self._container.resolve(token, module=self._container.module_graph.root_key)
        finally:
            self._container.scope_manager.pop_application(application_token)

    def resolve(self, token: object) -> Any:
        """Alias for app.get()."""
        return self.get(token)

    async def init(self) -> ApplicationContext:
        """Initialize asynchronous providers and lifecycle hooks."""

        if self._lifecycle_manager is not None:
            await self._lifecycle_manager.startup()
        return self

    async def close(self) -> None:
        """Trigger the application shutdown sequence.

        Mainly used for graceful teardown in tests.
        """
        if self._lifecycle_manager is not None:
            await self._lifecycle_manager.shutdown()


class Application(ApplicationContext):
    """A high-level application wrapper for HTTP services.

    This class extends the ApplicationContext with an HTTP server instance managed
    via an AbstractHttpAdapter.
    """

    def __init__(
        self,
        adapter: AbstractHttpAdapter,
        container: Container,
        lifecycle_manager: LifecycleManager | None = None,
        route_contracts: tuple[RouteContract, ...] = (),
        execution_plans: tuple[ExecutionPlan, ...] = (),
    ) -> None:
        super().__init__(container, lifecycle_manager)
        self._adapter = adapter
        self._route_contracts = route_contracts
        self._execution_plans = execution_plans

    def get_http_adapter(self) -> AbstractHttpAdapter:
        """Accessor for the underlying HTTP framework adapter."""
        return self._adapter

    def get_http_server(self) -> Any:
        """Accessor for the underlying framework instance (e.g., Starlette App)."""
        return self._adapter.get_instance()

    @property
    def route_contracts(self) -> tuple[RouteContract, ...]:
        """Accessor for the compiled route contracts registered on the app."""
        return self._route_contracts

    @property
    def execution_plans(self) -> tuple[ExecutionPlan, ...]:
        """Accessor for the compiled route execution plans registered on the app."""
        return self._execution_plans

    def snapshot_routes(self) -> tuple[dict[str, object], ...]:
        """Return a deterministic snapshot of the compiled application routes."""
        from ..platform.http.registry import snapshot_route_contracts

        return snapshot_route_contracts(self._route_contracts)

    def diff_routes(
        self,
        previous_snapshot: Sequence[Mapping[str, object]],
    ) -> tuple[dict[str, object], ...]:
        """Compare a previous route snapshot against the current application routes."""
        from ..platform.http.registry import diff_route_snapshots

        return diff_route_snapshots(previous_snapshot, self.snapshot_routes())

    def enable_cors(self, options: CorsOptions | None = None) -> None:
        """Register Starlette's CORS middleware on the application."""
        from starlette.middleware.cors import CORSMiddleware

        from ..security.cors import CorsOptions

        resolved = options or CorsOptions()
        allow_origins = (
            [resolved.origins] if isinstance(resolved.origins, str) else resolved.origins
        )
        self._adapter.add_middleware(
            CORSMiddleware,
            allow_origins=allow_origins,
            allow_methods=resolved.methods,
            allow_headers=resolved.allowed_headers,
            expose_headers=resolved.exposed_headers,
            allow_credentials=resolved.credentials,
            max_age=resolved.max_age,
        )

    def enable_swagger(
        self,
        path: str,
        document: dict[str, object],
        *,
        swagger_ui_path: str | None = None,
    ) -> None:
        """Register OpenAPI JSON and Swagger UI routes."""
        from ..openapi.swagger_ui import SwaggerModule

        SwaggerModule.setup(
            self,
            path,
            document,
            swagger_ui_path=swagger_ui_path,
        )

    async def listen(
        self, port: int, host: str = "127.0.0.1", reload: bool = False, **kwargs: Any
    ) -> None:
        """Start the ASGI server asynchronously via the adapter."""
        await self._adapter.listen(port, host=host, reload=reload, **kwargs)

    @property
    def routes(self) -> Mapping[str, list[object]]:
        """Accessor for the registered routes (by path)."""
        res: dict[str, list[object]] = {}
        instance = self.get_http_server()
        if hasattr(instance, "routes"):
            for route in instance.routes:
                path = getattr(route, "path", "")
                if path:
                    res.setdefault(path, []).append(route)
        return res

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        """Forward ASGI calls directly to the underlying HTTP adapter."""
        await self._adapter(scope, receive, send)
