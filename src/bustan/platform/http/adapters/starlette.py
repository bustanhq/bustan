"""Starlette adapter for Bustan request handling."""

from __future__ import annotations

import inspect
from dataclasses import asdict, is_dataclass
from typing import TYPE_CHECKING, Any

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from ....core.module.dynamic import ModuleKey
from ....core.ioc.container import Container
from ....core.errors import BadRequestException, GuardRejectedError, ParameterBindingError
from ..params import (
    BoundParameter,
    HandlerBindingPlan,
    ParameterSource,
    bind_handler_parameters,
    separate_bound_parameters,
)
from ....pipeline.context import HandlerContext, ParameterContext, RequestContext
from ....pipeline.filters import handle_exception
from ....pipeline.guards import run_guards
from ....pipeline.interceptors import call_with_interceptors
from ....pipeline.metadata import PipelineMetadata
from ....pipeline.pipes import run_pipes
from ..metadata import ControllerRouteDefinition
from ..controller_factory import ControllerFactory

if TYPE_CHECKING:
    from ....testing.overrides import PipelineOverrideRegistry


def coerce_response(value: object) -> Response:
    """Convert a handler return value into a concrete Response instance."""

    if isinstance(value, Response):
        return value

    if value is None:
        return Response(status_code=204)

    if is_dataclass(value) and not isinstance(value, type):
        return JSONResponse(asdict(value))

    if isinstance(value, (dict, list)):
        return JSONResponse(value)

    raise TypeError(f"Unsupported handler return type: {type(value).__name__}")


def create_starlette_endpoint(
    container: Container,
    module_key: ModuleKey,
    controller_cls: type[object],
    route_definition: ControllerRouteDefinition,
    binding_plan: HandlerBindingPlan,
    pipeline_metadata: PipelineMetadata,
    pipeline_override_registry: PipelineOverrideRegistry | None = None,
) -> Any:
    """Create the Starlette endpoint callable for one controller handler."""

    factory = ControllerFactory(
        container,
        pipeline_override_registry=pipeline_override_registry,
    )
    is_async_handler = inspect.iscoroutinefunction(route_definition.handler)

    async def endpoint(request: Request) -> Response:
        controller_instance = factory.instantiate(
            controller_cls, module=module_key, request=request
        )
        handler = getattr(controller_instance, route_definition.handler_name)

        request_context = RequestContext(
            request=request,
            module=module_key,
            controller_type=controller_cls,
            controller=controller_instance,
            route=route_definition,
            container=container,
        )

        # Resolve the pipeline for this specific request
        resolved_pipeline = factory.resolve_pipeline(
            pipeline_metadata, module=module_key, request=request
        )

        try:
            await run_guards(request_context, resolved_pipeline.guards)
            bound_parameters = await bind_handler_parameters(request, binding_plan)

            # Apply pipes
            piped_parameters = await _apply_pipes(
                bound_parameters, request_context, resolved_pipeline.pipes
            )
            positional_arguments, keyword_arguments = separate_bound_parameters(piped_parameters)

            handler_context = HandlerContext(
                request_context=request_context,
                arguments=positional_arguments,
                keyword_arguments=keyword_arguments,
            )

            async def final_handler() -> object:
                if is_async_handler:
                    return await handler(*positional_arguments, **keyword_arguments)
                return await run_in_threadpool(
                    handler,
                    *positional_arguments,
                    **keyword_arguments,
                )

            result = await call_with_interceptors(
                handler_context, resolved_pipeline.interceptors, final_handler
            )
        except Exception as exc:
            filtered_result = await handle_exception(
                request_context, exc, resolved_pipeline.filters
            )
            if filtered_result is not None:
                response = coerce_response(filtered_result)
                _apply_rate_limit_headers(request, response)
                return response

            # Fallback to standard error responses for common exceptions if not handled by filters
            if isinstance(exc, BadRequestException):
                payload = {"detail": str(exc)}
                if exc.field is not None:
                    payload["field"] = exc.field
                response = JSONResponse(payload, status_code=400)
                _apply_rate_limit_headers(request, response)
                return response
            if isinstance(exc, ParameterBindingError):
                response = JSONResponse({"detail": str(exc)}, status_code=400)
                _apply_rate_limit_headers(request, response)
                return response
            if isinstance(exc, GuardRejectedError):
                status_code = 429 if getattr(request.state, "rate_limit_exceeded", False) else 403
                detail = "Too Many Requests" if status_code == 429 else str(exc)
                response = JSONResponse({"detail": detail}, status_code=status_code)
                _apply_rate_limit_headers(request, response)
                return response
            raise

        response = coerce_response(result)
        _apply_rate_limit_headers(request, response)
        return response

    endpoint.__name__ = route_definition.route.name
    return endpoint


def _apply_rate_limit_headers(request: Request, response: Response) -> None:
    if not hasattr(request.state, "rate_limit_limit"):
        return
    response.headers["X-RateLimit-Limit"] = str(request.state.rate_limit_limit)
    response.headers["X-RateLimit-Remaining"] = str(request.state.rate_limit_remaining)
    response.headers["X-RateLimit-Reset"] = str(request.state.rate_limit_reset)


async def _apply_pipes(
    bound_parameters: tuple[Any, ...],
    request_context: RequestContext,
    pipes: tuple[Any, ...],
) -> tuple[Any, ...]:
    if not pipes:
        return bound_parameters

    transformed_parameters: list[Any] = []
    for bound_parameter in bound_parameters:
        if bound_parameter.binding.source is ParameterSource.REQUEST:
            transformed_parameters.append(bound_parameter)
            continue

        transformed_value = await run_pipes(
            bound_parameter.value,
            ParameterContext(
                request_context=request_context,
                name=bound_parameter.binding.name,
                source=bound_parameter.binding.source.value,
                annotation=bound_parameter.binding.annotation,
                value=bound_parameter.value,
            ),
            pipes,
        )
        transformed_parameters.append(
            BoundParameter(binding=bound_parameter.binding, value=transformed_value)
        )

    return tuple(transformed_parameters)
