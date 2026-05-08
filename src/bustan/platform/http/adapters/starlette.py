"""Starlette adapter for Bustan request handling."""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Any, cast

from starlette.middleware.base import RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from ....core.ioc.container import Container
from ....pipeline.middleware import Middleware, ResolvedRouteMiddleware
from ..abstractions import StarletteHttpRequest, to_starlette_response
from ..controller_factory import ControllerFactory
from ..execution import ExecutionPlan, execute_http_exception, execute_http_route

if TYPE_CHECKING:
    from ....testing.overrides import PipelineOverrideRegistry


def create_starlette_endpoint(
    container: Container,
    execution_plan: ExecutionPlan,
    middleware_chain: tuple[ResolvedRouteMiddleware, ...],
    pipeline_override_registry: PipelineOverrideRegistry | None = None,
) -> Any:
    """Create the Starlette endpoint callable for one controller handler."""

    factory = ControllerFactory(
        container,
        pipeline_override_registry=pipeline_override_registry,
    )

    async def endpoint(request: Request) -> Response:
        async def handle_route_exception(current_request: Request, error: Exception) -> Response:
            execution_result = await execute_http_exception(
                application_runtime=getattr(
                    current_request.app.state,
                    "bustan_application",
                    current_request.app,
                ),
                container=container,
                factory=factory,
                execution_plan=execution_plan,
                request=StarletteHttpRequest(current_request),
                native_request=current_request,
                error=error,
            )
            return to_starlette_response(execution_result.response)

        async def execute_handler(current_request: Request) -> Response:
            execution_result = await execute_http_route(
                application_runtime=getattr(
                    current_request.app.state,
                    "bustan_application",
                    current_request.app,
                ),
                container=container,
                factory=factory,
                execution_plan=execution_plan,
                request=StarletteHttpRequest(current_request),
                native_request=current_request,
            )
            return to_starlette_response(execution_result.response)

        return await _run_route_middleware(
            request,
            middleware_chain,
            factory,
            execute_handler,
            exception_handler=handle_route_exception,
        )

    endpoint.__name__ = execution_plan.route_definition.route.name
    return endpoint


async def _run_route_middleware(
    request: Request,
    middleware_chain: tuple[ResolvedRouteMiddleware, ...],
    factory: ControllerFactory,
    terminal_handler: RequestResponseEndpoint,
    *,
    exception_handler=None,
) -> Response:
    async def invoke(index: int, current_request: Request) -> Response:
        try:
            if index >= len(middleware_chain):
                return await terminal_handler(current_request)

            entry = middleware_chain[index]

            async def call_next(next_request: Request) -> Response:
                return await invoke(index + 1, next_request)

            middleware_ref = entry.middleware
            if isinstance(middleware_ref, type) or isinstance(middleware_ref, Middleware):
                middleware = factory.resolve_components(
                    (middleware_ref,),
                    Middleware,
                    module=entry.declaring_module,
                    request=current_request,
                    kind="middleware",
                )[0]
                return await middleware.use(current_request, call_next)

            result = cast(Any, middleware_ref)(current_request, call_next)
            if inspect.isawaitable(result):
                return await cast(Any, result)
            return cast(Response, result)
        except Exception as exc:
            if exception_handler is None:
                raise
            return await exception_handler(current_request, exc)

    return await invoke(0, request)
