"""Public application wrapper and context for the Bustan framework."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Any, Protocol, overload, runtime_checkable

if TYPE_CHECKING:
    from ..adapters.asgi.types import Receive, Scope, Send
    from ..kernel.ioc.container import Container
    from ..kernel.ioc.tokens import InjectionToken
    from ..kernel.lifecycle.manager import LifecycleManager
    from ..kernel.module.graph import ModuleGraph
    from ..runtime.adapter import AbstractHttpAdapter
    from ..runtime.compiler import RouteContract
    from ..runtime.execution import ExecutionPlan
    from ..security.cors import CorsOptions

# The application teardown, as an adapter receives it: called with the name of the
# signal that asked the process to stop, or with nothing when a caller asked instead.
type _ShutdownSequence = Callable[[str | None], Awaitable[None]]


@runtime_checkable
class SupportsGracefulShutdown(Protocol):
    """An adapter that drains its server before the application is torn down.

    The adapter port says how to start and stop a server, not what a server owes the
    requests it has already accepted. An adapter that can answer that implements this,
    and is handed the application teardown so that draining and tearing down are one
    sequence: the hooks run once the last in-flight request has finished, and the
    listening socket is released once the hooks have. An adapter that does not is
    stopped and torn down as two steps, which is all its transport can promise.
    """

    def prepare_graceful_shutdown(
        self, shut_down: _ShutdownSequence, drain_timeout: float | None = None
    ) -> None:
        """Take the application teardown to run once the server has drained."""


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
        # Set by the application factory when the context is assembled into something
        # that serves HTTP. The context is what APPLICATION answers with, and it
        # describes a container rather than a transport, so it names the HTTP
        # application rather than being one.
        self._http_application: Application | None = None

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

    @property
    def lifecycle_manager(self) -> LifecycleManager | None:
        """Accessor for the manager that runs startup and shutdown, if there is one.

        A context built without one never runs a lifecycle hook, so `init()` and
        `close()` on it do nothing.
        """
        return self._lifecycle_manager

    @property
    def http_application(self) -> Application | None:
        """Accessor for the HTTP application assembled around this context.

        A context created on its own serves no HTTP traffic and has none, which is how
        a caller tells the two apart without inspecting either.
        """
        return self._http_application

    @overload
    def get[T](self, token: InjectionToken[T]) -> T: ...

    @overload
    def get(self, token: object) -> Any: ...

    def get(self, token: object) -> Any:
        """Resolve a provider as though no request were being served.

        An ``InjectionToken[T]`` types what comes back: resolving through one yields a
        ``T``, and assigning it to anything else is a type error rather than something
        a cast has to assert. Every other token - a class, a bare string, an enum
        member - resolves unchecked, exactly as it did before.

        Anything scoped to a request is refused here, whether or not a request happens
        to be in flight, so a provider resolved this way can never capture one caller's
        state and hand it to the next. To reach a request-scoped provider from inside a
        handler, a guard or an interceptor, inject `ModuleRef` and call its `get()`:
        that resolves against the request currently being served.
        """
        application_token = self._container.scope_manager.push_application(self)
        try:
            return self._container.resolve(token, module=self._container.module_graph.root_key)
        finally:
            self._container.scope_manager.pop_application(application_token)

    @overload
    def resolve[T](self, token: InjectionToken[T]) -> T: ...

    @overload
    def resolve(self, token: object) -> Any: ...

    def resolve(self, token: object) -> Any:
        """Alias for app.get(), with the same non-request semantics and the same typing."""
        return self.get(token)

    async def init(self) -> ApplicationContext:
        """Initialize asynchronous providers and lifecycle hooks.

        The application is the running application for the whole of startup, so a
        provider built eagerly here may inject `APPLICATION` exactly as one built
        lazily during a request can.
        """

        if self._lifecycle_manager is not None:
            application_token = self._container.scope_manager.push_application(self)
            try:
                await self._lifecycle_manager.startup()
            finally:
                self._container.scope_manager.pop_application(application_token)
        return self

    async def close(self) -> None:
        """Run the application shutdown sequence, destroying what startup built.

        A context serves no HTTP traffic, so there is nothing to drain and nothing that
        asked it to stop: the teardown hooks run immediately and receive no signal name.
        """

        await self._run_shutdown(None)

    async def _run_shutdown(self, signal: str | None) -> None:
        """Run every teardown hook, telling them which signal asked, if one did.

        The application is the running application for the whole of the teardown, in the
        same way it is for the whole of startup, so a hook may still inject
        ``APPLICATION`` while the instances it names are being destroyed.
        """

        if self._lifecycle_manager is not None:
            application_token = self._container.scope_manager.push_application(self)
            try:
                await self._lifecycle_manager.shutdown(signal=signal)
            finally:
                self._container.scope_manager.pop_application(application_token)


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
        # Told here rather than when a server starts, because a caller may stop an
        # application it never started this way, and the sequence is the same one.
        if isinstance(adapter, SupportsGracefulShutdown):
            adapter.prepare_graceful_shutdown(self._run_shutdown)

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
        from ..runtime.registry import snapshot_route_contracts

        return snapshot_route_contracts(self._route_contracts)

    def diff_routes(
        self,
        previous_snapshot: Sequence[Mapping[str, object]],
    ) -> tuple[dict[str, object], ...]:
        """Compare a previous route snapshot against the current application routes."""
        from ..runtime.registry import diff_route_snapshots

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
        self,
        port: int,
        host: str = "127.0.0.1",
        reload: bool = False,
        *,
        drain_timeout: float | None = None,
        **kwargs: Any,
    ) -> None:
        """Serve the application until the server is signalled or stopped.

        A ``SIGINT`` or a ``SIGTERM`` arriving while this is serving stops the server
        gracefully. New requests are refused while the requests already in flight are
        given ``drain_timeout`` seconds to finish, then the shutdown hooks run and are
        told which signal arrived, and only then is the listening port released. A
        request that outlasts the window is cancelled rather than allowed to hold the
        process open. Left out, ``drain_timeout`` is whatever the adapter was built
        with; an adapter whose transport cannot drain serves and stops as before.
        """

        if drain_timeout is not None and isinstance(self._adapter, SupportsGracefulShutdown):
            self._adapter.prepare_graceful_shutdown(self._run_shutdown, drain_timeout)
        await self._adapter.listen(port, host=host, reload=reload, **kwargs)

    async def close(self) -> None:
        """Stop the server, if one is running, and run the application shutdown sequence.

        A running server is stopped the way a signal stops it, and this returns once it
        has released its port, so a caller may bind that port again or start the
        application afresh. With no server running there is nothing to drain and this is
        the teardown on its own.
        """

        await self._adapter.stop()
        # The adapter runs the teardown itself when it drained a server, and that
        # teardown is what leaves nothing here to do. This is the path where no server
        # was running, and it is safe either way: a second teardown is a no-op.
        await self._run_shutdown(None)

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

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Forward ASGI calls directly to the underlying HTTP adapter.

        The parameters spell the ASGI vocabulary exactly as the transport declares it,
        so this object is assignable wherever a server or an in-process client asks for
        an ASGI application. Narrowing any of them would make the framework's own
        composition a type error for everyone outside this repository.
        """

        await self._adapter(scope, receive, send)
