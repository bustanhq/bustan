"""Adapter-neutral HTTP execution planning and runtime orchestration."""

from __future__ import annotations

import inspect
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import partial
from inspect import iscoroutinefunction
from typing import TYPE_CHECKING, Any, cast

from anyio import to_thread

from ..contracts import HttpRequest, HttpResponse, RouteHandler
from ..kernel.ioc.container import Container
from ..kernel.module.dynamic import ModuleKey
from ..observability.observability import ObservabilityHooks
from ..pipeline.context import ExecutionContext
from ..pipeline.filters import handle_exception
from ..pipeline.guards import run_guards
from ..pipeline.interceptors import call_with_interceptors
from ..pipeline.middleware import Middleware, ResolvedRouteMiddleware
from ..pipeline.pipes import Pipe, run_pipes
from .compiler import PipelinePlan, PolicyPlan, ResponsePlan, RouteContract
from .controller_factory import ControllerFactory, ResolvedPipeline
from .metadata import ControllerRouteDefinition
from .params import (
    BoundParameter,
    HandlerBindingPlan,
    ParameterSource,
    bind_handler_parameters,
    separate_bound_parameters,
)
from .responses import CoercedResponse, ResponseHandler

if TYPE_CHECKING:
    from ..testing.overrides import PipelineOverrideRegistry

RuntimeResponse = CoercedResponse
RouteExceptionHandler = Callable[[HttpRequest, Exception], Awaitable[RuntimeResponse]]
_EXCEPTION_RESPONSE_PLAN = ResponsePlan(declared_type=None, default_status_code=200)
_LOGGER = logging.getLogger(__name__)
_INTERNAL_SERVER_ERROR_DETAIL = "Internal server error"


@dataclass(frozen=True, slots=True)
class ExecutionPlan:
    """Compiled runtime plan consumed by HTTP adapters."""

    route_contract: RouteContract
    module_key: ModuleKey
    controller_cls: type[object]
    route_definition: ControllerRouteDefinition
    binding_plan: HandlerBindingPlan
    pipeline_plan: PipelinePlan
    response_plan: ResponsePlan
    policy_plan: PolicyPlan
    is_async_handler: bool

    @property
    def handler_name(self) -> str:
        return self.route_definition.handler_name

    @property
    def method(self) -> str:
        return self.route_contract.method

    @property
    def path(self) -> str:
        return self.route_contract.path


@dataclass(frozen=True, slots=True)
class HttpExecutionResult:
    """Result produced by the adapter-neutral HTTP execution engine."""

    response: RuntimeResponse
    context: ExecutionContext | None
    error: Exception | None = None


def compile_execution_plan(route_contract: RouteContract) -> ExecutionPlan:
    """Compile a route contract into its runtime execution plan."""

    return ExecutionPlan(
        route_contract=route_contract,
        module_key=route_contract.module_key,
        controller_cls=route_contract.controller_cls,
        route_definition=route_contract.route_definition,
        binding_plan=route_contract.binding_plan,
        pipeline_plan=route_contract.pipeline_plan,
        response_plan=route_contract.response_plan,
        policy_plan=route_contract.policy_plan,
        is_async_handler=iscoroutinefunction(route_contract.route_definition.handler),
    )


def compile_execution_plans(
    route_contracts: tuple[RouteContract, ...],
) -> tuple[ExecutionPlan, ...]:
    """Compile stable execution plans for all discovered route contracts."""

    return tuple(compile_execution_plan(route_contract) for route_contract in route_contracts)


def create_route_handler(
    container: Container,
    execution_plan: ExecutionPlan,
    middleware_chain: tuple[ResolvedRouteMiddleware, ...] = (),
    pipeline_override_registry: PipelineOverrideRegistry | None = None,
) -> RouteHandler:
    """Build the framework's entry point for one compiled route.

    The returned handler is what a transport adapter calls once it has converted a
    request, and it owns the whole request: the scopes are pushed before the first
    middleware runs and released only after the last one has returned. That is what
    lets a middleware resolving a request-scoped provider after ``call_next`` see the
    instance the handler saw, rather than a second one built once the scope had
    already closed underneath it.
    """

    factory = ControllerFactory(
        container,
        pipeline_override_registry=pipeline_override_registry,
    )

    async def run_route(request: HttpRequest) -> RuntimeResponse:
        result = await execute_http_route(
            application_runtime=request.app,
            container=container,
            factory=factory,
            execution_plan=execution_plan,
            request=request,
        )
        return result.response

    async def render_error(request: HttpRequest, error: Exception) -> RuntimeResponse:
        result = await execute_http_exception(
            application_runtime=request.app,
            container=container,
            factory=factory,
            execution_plan=execution_plan,
            request=request,
            error=error,
        )
        return result.response

    async def handle(request: HttpRequest) -> RuntimeResponse:
        request_token = container.scope_manager.push_request(request)
        application_token = container.scope_manager.push_application(
            _application_runtime(request.app)
        )
        try:
            return await run_middleware_chain(
                request,
                middleware_chain,
                factory,
                run_route,
                exception_handler=render_error,
            )
        finally:
            # The request is over only once the outermost middleware has returned, so
            # what was scoped to it is released here rather than inside the route.
            container.scope_manager.clear_request_state(request)
            container.scope_manager.pop_application(application_token)
            container.scope_manager.pop_request(request_token)

    return handle


async def run_middleware_chain(
    request: HttpRequest,
    middleware_chain: tuple[ResolvedRouteMiddleware, ...],
    factory: ControllerFactory,
    terminal_handler: RouteHandler,
    *,
    exception_handler: RouteExceptionHandler | None = None,
) -> RuntimeResponse:
    """Run the route's middleware chain, ending in *terminal_handler*."""

    async def invoke(index: int, current_request: HttpRequest) -> RuntimeResponse:
        try:
            if index >= len(middleware_chain):
                return cast(RuntimeResponse, await terminal_handler(current_request))

            entry = middleware_chain[index]

            async def call_next(next_request: HttpRequest) -> RuntimeResponse:
                return await invoke(index + 1, next_request)

            middleware_ref = entry.middleware
            if isinstance(middleware_ref, type | Middleware):
                middleware = factory.resolve_components(
                    (middleware_ref,),
                    Middleware,
                    module=entry.declaring_module,
                    request=current_request,
                    kind="middleware",
                )[0]
                return cast(RuntimeResponse, await middleware.use(current_request, call_next))

            result = cast(Any, middleware_ref)(current_request, call_next)
            if inspect.isawaitable(result):
                return cast(RuntimeResponse, await cast(Any, result))
            return cast(RuntimeResponse, result)
        except Exception as exc:
            if exception_handler is None:
                raise
            return await exception_handler(current_request, exc)

    return await invoke(0, request)


async def execute_http_route(
    *,
    application_runtime: object,
    container: Container,
    factory: ControllerFactory,
    execution_plan: ExecutionPlan,
    request: HttpRequest,
) -> HttpExecutionResult:
    """Execute one compiled HTTP route through the shared runtime pipeline."""

    # The request is bound for the whole execution, not merely for the duration of one
    # resolve call, so anything running inside the route - a handler, a guard, an
    # interceptor - can reach the request being served and the providers scoped to it.
    request_token = container.scope_manager.push_request(request)
    application_token = container.scope_manager.push_application(
        _application_runtime(application_runtime)
    )
    response_context = HttpResponse()
    response_token = container.scope_manager.push_response(response_context)
    response_handler = ResponseHandler()
    observability = ObservabilityHooks.current()
    context: ExecutionContext | None = None
    resolved_pipeline: ResolvedPipeline | None = None
    observation = None

    try:
        controller_instance = await factory.instantiate_async(
            execution_plan.controller_cls,
            module=execution_plan.module_key,
            request=request,
        )
        handler = getattr(controller_instance, execution_plan.handler_name)
        context = ExecutionContext.create_http(
            request=request,
            response=response_context,
            handler=execution_plan.route_definition.handler,
            controller_cls=execution_plan.controller_cls,
            module=execution_plan.module_key,
            controller=controller_instance,
            container=container,
            route=execution_plan.route_definition,
            route_contract=execution_plan.route_contract,
            policy_plan=execution_plan.policy_plan,
        )
        resolved_pipeline = await factory.resolve_pipeline_async(
            execution_plan.pipeline_plan,
            module=execution_plan.module_key,
            request=request,
        )
        observation = observability.start_request(context)

        await run_guards(context, resolved_pipeline.guards)
        bound_parameters = await bind_handler_parameters(
            request,
            execution_plan.binding_plan,
            context,
        )
        piped_parameters = await _apply_pipes(
            bound_parameters,
            context,
            resolved_pipeline.pipes,
            execution_plan.binding_plan,
        )
        positional_arguments, keyword_arguments = separate_bound_parameters(piped_parameters)

        async def final_handler() -> object:
            if execution_plan.is_async_handler:
                return await handler(*positional_arguments, **keyword_arguments)
            return await to_thread.run_sync(
                partial(handler, *positional_arguments, **keyword_arguments)
            )

        result = await call_with_interceptors(
            context,
            resolved_pipeline.interceptors,
            final_handler,
        )
        response = response_handler.write(result=result, response_plan=execution_plan.response_plan)
        response = _merge_response_context(
            response_context,
            response,
            default_status_code=execution_plan.response_plan.default_status_code,
        )
        _apply_rate_limit_headers(request, response)

        if observation is not None:
            observability.finish_request(
                observation,
                status_code=_response_status_code(response),
            )
        return HttpExecutionResult(response=response, context=context)
    except Exception as exc:
        response = await _render_failure(
            exc,
            context=context,
            resolved_pipeline=resolved_pipeline,
            response_handler=response_handler,
            response_context=response_context,
            request=request,
        )
        if observation is not None:
            observability.finish_request(
                observation,
                status_code=_response_status_code(response),
                error=exc,
            )
        return HttpExecutionResult(response=response, context=context, error=exc)
    finally:
        container.scope_manager.pop_response(response_token)
        container.scope_manager.pop_application(application_token)
        container.scope_manager.pop_request(request_token)


async def execute_http_exception(
    *,
    application_runtime: object,
    container: Container,
    factory: ControllerFactory,
    execution_plan: ExecutionPlan,
    request: HttpRequest,
    error: Exception,
) -> HttpExecutionResult:
    """Render an exception through the route's compiled filter chain.

    A failure while assembling that chain is rendered exactly as the main path renders
    one, so a request that failed in a middleware is answered with the same document,
    in the same content type, as one that failed inside its handler, and a resolution
    failure never reaches the caller as a traceback.
    """

    request_token = container.scope_manager.push_request(request)
    application_token = container.scope_manager.push_application(
        _application_runtime(application_runtime)
    )
    response_context = HttpResponse()
    response_token = container.scope_manager.push_response(response_context)
    response_handler = ResponseHandler()
    observability = ObservabilityHooks.current()
    observation = None
    context: ExecutionContext | None = None
    resolved_pipeline: ResolvedPipeline | None = None

    try:
        controller_instance = await factory.instantiate_async(
            execution_plan.controller_cls,
            module=execution_plan.module_key,
            request=request,
        )
        context = ExecutionContext.create_http(
            request=request,
            response=response_context,
            handler=execution_plan.route_definition.handler,
            controller_cls=execution_plan.controller_cls,
            module=execution_plan.module_key,
            controller=controller_instance,
            container=container,
            route=execution_plan.route_definition,
            route_contract=execution_plan.route_contract,
            policy_plan=execution_plan.policy_plan,
        )
        resolved_pipeline = await factory.resolve_pipeline_async(
            execution_plan.pipeline_plan,
            module=execution_plan.module_key,
            request=request,
        )
        observation = observability.start_request(context)
        filtered_result = await handle_exception(context, error, resolved_pipeline.filters)
        response = response_handler.write(
            result=filtered_result,
            response_plan=_EXCEPTION_RESPONSE_PLAN,
        )
        response = _merge_response_context(
            response_context,
            response,
            default_status_code=_EXCEPTION_RESPONSE_PLAN.default_status_code,
        )
        _apply_rate_limit_headers(request, response)
        observability.finish_request(
            observation,
            status_code=_response_status_code(response),
            error=error,
        )
        return HttpExecutionResult(response=response, context=context, error=error)
    except Exception as exc:
        response = await _render_failure(
            exc,
            context=context,
            resolved_pipeline=resolved_pipeline,
            response_handler=response_handler,
            response_context=response_context,
            request=request,
        )
        if observation is not None:
            observability.finish_request(
                observation,
                status_code=_response_status_code(response),
                error=exc,
            )
        return HttpExecutionResult(response=response, context=context, error=error)
    finally:
        container.scope_manager.pop_response(response_token)
        container.scope_manager.pop_application(application_token)
        container.scope_manager.pop_request(request_token)


async def _render_failure(
    exc: Exception,
    *,
    context: ExecutionContext | None,
    resolved_pipeline: ResolvedPipeline | None,
    response_handler: ResponseHandler,
    response_context: HttpResponse,
    request: HttpRequest,
) -> RuntimeResponse:
    """Turn an exception the route could not handle itself into a client response.

    Once the route's filters have been resolved they are given the exception; before
    that they do not exist, so the failure is logged where an operator can read it and
    answered with an opaque 500 that says nothing about the framework's internals.
    """

    if context is not None and resolved_pipeline is not None:
        filtered_result = await handle_exception(context, exc, resolved_pipeline.filters)
        response = response_handler.write(
            result=filtered_result,
            response_plan=_EXCEPTION_RESPONSE_PLAN,
        )
    else:
        _LOGGER.exception("Unhandled exception during request setup", exc_info=exc)
        response = HttpResponse.json({"detail": _INTERNAL_SERVER_ERROR_DETAIL}, status_code=500)

    response = _merge_response_context(
        response_context,
        response,
        default_status_code=_EXCEPTION_RESPONSE_PLAN.default_status_code,
    )
    _apply_rate_limit_headers(request, response)
    return response


def _application_runtime(application_runtime: object) -> object:
    """Return the Bustan application behind whatever the transport handed over.

    ``APPLICATION`` names the application a provider is running inside, and that has
    to be the same object whichever way the resolution was entered. An adapter that
    passes its own server instance is unwrapped to the runtime attached to it, so a
    provider is never handed the web server on one path and the application on another.
    """

    from ..app.application import ApplicationContext

    if isinstance(application_runtime, ApplicationContext):
        return application_runtime
    state = getattr(application_runtime, "state", None)
    attached = getattr(state, "bustan_application", None)
    if isinstance(attached, ApplicationContext):
        return attached
    return application_runtime


async def _apply_pipes(
    bound_parameters: tuple[BoundParameter, ...],
    context: ExecutionContext,
    pipes: tuple[Pipe, ...],
    binding_plan: HandlerBindingPlan,
) -> tuple[BoundParameter, ...]:
    if not pipes and binding_plan.validation_mode.value != "auto":
        return bound_parameters

    transformed_parameters: list[BoundParameter] = []
    for bound_parameter in bound_parameters:
        if bound_parameter.binding.source is ParameterSource.REQUEST:
            transformed_parameters.append(bound_parameter)
            continue

        transformed_value = await run_pipes(
            bound_parameter.value,
            context.with_parameter(
                name=bound_parameter.binding.name,
                source=bound_parameter.binding.source.value,
                annotation=bound_parameter.binding.annotation,
                value=bound_parameter.value,
                validation_mode=binding_plan.validation_mode.value,
                validate_custom_decorators=binding_plan.validate_custom_decorators,
            ),
            pipes,
        )
        transformed_parameters.append(
            BoundParameter(binding=bound_parameter.binding, value=transformed_value)
        )

    return tuple(transformed_parameters)


def _apply_rate_limit_headers(request: HttpRequest, response: RuntimeResponse) -> None:
    rate_limit = request.slots.rate_limit
    if rate_limit is None:
        return

    response.headers["X-RateLimit-Limit"] = str(rate_limit.limit)
    response.headers["X-RateLimit-Remaining"] = str(rate_limit.remaining)
    response.headers["X-RateLimit-Reset"] = str(rate_limit.reset)


def _response_status_code(response: RuntimeResponse) -> int:
    return int(response.status_code)


def _merge_response_context(
    response_context: HttpResponse,
    response: RuntimeResponse,
    *,
    default_status_code: int,
) -> RuntimeResponse:
    for header_name, header_value in response_context.headers.items():
        response.headers[header_name] = header_value

    if response_context.status_code != 200 and response.status_code in {
        200,
        default_status_code,
    }:
        response.status_code = response_context.status_code

    return response


__all__ = [
    "ExecutionPlan",
    "HttpExecutionResult",
    "RouteExceptionHandler",
    "RuntimeResponse",
    "compile_execution_plan",
    "compile_execution_plans",
    "create_route_handler",
    "execute_http_exception",
    "execute_http_route",
    "run_middleware_chain",
]
