"""Adapter-neutral HTTP execution planning and runtime orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from typing import cast

from anyio import to_thread
from starlette.requests import Request
from starlette.responses import Response

from ...core.ioc.container import Container
from ...core.module.dynamic import ModuleKey
from ...logger.observability import ObservabilityHooks
from ...pipeline.context import ExecutionContext
from ...pipeline.filters import handle_exception
from ...pipeline.guards import run_guards
from ...pipeline.interceptors import call_with_interceptors
from ...pipeline.pipes import Pipe, run_pipes
from .abstractions import HttpFileResponse, HttpRequest, HttpResponse, HttpStreamResponse
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
from .responses import ResponseHandler

RuntimeResponse = HttpResponse | HttpStreamResponse | HttpFileResponse | Response
_EXCEPTION_RESPONSE_PLAN = ResponsePlan(declared_type=None, default_status_code=200)


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
        is_async_handler=route_contract.route_definition.handler.__code__.co_flags & 0x80 != 0,
    )


def compile_execution_plans(route_contracts: tuple[RouteContract, ...]) -> tuple[ExecutionPlan, ...]:
    """Compile stable execution plans for all discovered route contracts."""

    return tuple(compile_execution_plan(route_contract) for route_contract in route_contracts)


async def execute_http_route(
    *,
    application_runtime: object,
    container: Container,
    factory: ControllerFactory,
    execution_plan: ExecutionPlan,
    request: HttpRequest,
    native_request: object,
) -> HttpExecutionResult:
    """Execute one compiled HTTP route through the shared runtime pipeline."""

    application_token = container.scope_manager.push_application(application_runtime)
    response_handler = ResponseHandler()
    observability = ObservabilityHooks.current()
    context: ExecutionContext | None = None
    resolved_pipeline: ResolvedPipeline | None = None
    observation = None

    try:
        native_http_request = cast(Request, native_request)
        controller_instance = factory.instantiate(
            execution_plan.controller_cls,
            module=execution_plan.module_key,
            request=native_http_request,
        )
        handler = getattr(controller_instance, execution_plan.handler_name)
        context = ExecutionContext.create_http(
            request=request,
            response=None,
            handler=execution_plan.route_definition.handler,
            controller_cls=execution_plan.controller_cls,
            module=execution_plan.module_key,
            controller=controller_instance,
            container=container,
            route=execution_plan.route_definition,
            route_contract=execution_plan.route_contract,
            policy_plan=execution_plan.policy_plan,
        )
        resolved_pipeline = factory.resolve_pipeline(
            execution_plan.pipeline_plan,
            module=execution_plan.module_key,
            request=native_http_request,
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
            return await to_thread.run_sync(partial(handler, *positional_arguments, **keyword_arguments))

        result = await call_with_interceptors(
            context,
            resolved_pipeline.interceptors,
            final_handler,
        )
        response = response_handler.write(result=result, response_plan=execution_plan.response_plan)
        _apply_rate_limit_headers(request, response)

        if observation is not None:
            observability.finish_request(
                observation,
                status_code=_response_status_code(response),
            )
        return HttpExecutionResult(response=response, context=context)
    except Exception as exc:
        if context is not None and resolved_pipeline is not None:
            filtered_result = await handle_exception(context, exc, resolved_pipeline.filters)
            response = response_handler.write(
                result=filtered_result,
                response_plan=_EXCEPTION_RESPONSE_PLAN,
            )
        else:
            response = HttpResponse.json({"detail": str(exc)}, status_code=500)

        _apply_rate_limit_headers(request, response)
        if observation is not None:
            observability.finish_request(
                observation,
                status_code=_response_status_code(response),
                error=exc,
            )
        return HttpExecutionResult(response=response, context=context, error=exc)
    finally:
        container.scope_manager.pop_application(application_token)


async def execute_http_exception(
    *,
    application_runtime: object,
    container: Container,
    factory: ControllerFactory,
    execution_plan: ExecutionPlan,
    request: HttpRequest,
    native_request: object,
    error: Exception,
) -> HttpExecutionResult:
    """Render an exception through the route's compiled filter chain."""

    application_token = container.scope_manager.push_application(application_runtime)
    response_handler = ResponseHandler()
    observability = ObservabilityHooks.current()
    observation = None
    context: ExecutionContext | None = None

    try:
        native_http_request = cast(Request, native_request)
        controller_instance = factory.instantiate(
            execution_plan.controller_cls,
            module=execution_plan.module_key,
            request=native_http_request,
        )
        context = ExecutionContext.create_http(
            request=request,
            response=None,
            handler=execution_plan.route_definition.handler,
            controller_cls=execution_plan.controller_cls,
            module=execution_plan.module_key,
            controller=controller_instance,
            container=container,
            route=execution_plan.route_definition,
            route_contract=execution_plan.route_contract,
            policy_plan=execution_plan.policy_plan,
        )
        resolved_pipeline = factory.resolve_pipeline(
            execution_plan.pipeline_plan,
            module=execution_plan.module_key,
            request=native_http_request,
        )
        observation = observability.start_request(context)
        filtered_result = await handle_exception(context, error, resolved_pipeline.filters)
        response = response_handler.write(
            result=filtered_result,
            response_plan=_EXCEPTION_RESPONSE_PLAN,
        )
        _apply_rate_limit_headers(request, response)
        observability.finish_request(
            observation,
            status_code=_response_status_code(response),
            error=error,
        )
        return HttpExecutionResult(response=response, context=context, error=error)
    finally:
        container.scope_manager.pop_application(application_token)


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
    if not hasattr(request.state, "rate_limit_limit") or not hasattr(response, "headers"):
        return

    response.headers["X-RateLimit-Limit"] = str(request.state.rate_limit_limit)
    response.headers["X-RateLimit-Remaining"] = str(request.state.rate_limit_remaining)
    response.headers["X-RateLimit-Reset"] = str(request.state.rate_limit_reset)


def _response_status_code(response: RuntimeResponse) -> int:
    return int(getattr(response, "status_code", 200))


__all__ = [
    "ExecutionPlan",
    "HttpExecutionResult",
    "execute_http_exception",
    "compile_execution_plan",
    "compile_execution_plans",
    "execute_http_route",
]