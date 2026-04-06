"""Route compilation and request orchestration."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import TypeVar, cast

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from .container import Container
from .errors import (
    GuardRejectedError,
    InvalidPipelineError,
    ParameterBindingError,
    RouteDefinitionError,
)
from .metadata import (
    BUSTAN_PROVIDER_ATTR,
    ControllerRouteDefinition,
    PipelineMetadata,
    get_controller_metadata,
    get_controller_pipeline_metadata,
    get_handler_pipeline_metadata,
    iter_controller_routes,
    merge_pipeline_metadata,
)
from .utils import _join_paths, _qualname
from .module_graph import ModuleGraph
from .params import (
    BoundParameter,
    HandlerBindingPlan,
    ParameterSource,
    bind_handler_parameters,
    compile_parameter_bindings,
    separate_bound_parameters,
)
from .pipeline.context import HandlerContext, ParameterContext, RequestContext
from .pipeline.filters import ExceptionFilter, handle_exception
from .pipeline.guards import Guard, run_guards
from .pipeline.interceptors import Interceptor, call_with_interceptors
from .pipeline.pipes import Pipe, run_pipes
from .responses import coerce_response

Endpoint = Callable[[Request], Awaitable[Response]]
ComponentT = TypeVar("ComponentT")


def compile_routes(module_graph: ModuleGraph, container: Container) -> tuple[Route, ...]:
    """Compile controller metadata into Starlette Route objects."""

    seen_routes: dict[tuple[str, str], str] = {}
    compiled_routes: list[Route] = []

    for node in module_graph.nodes:
        for controller_cls in node.controllers:
            controller_metadata = get_controller_metadata(controller_cls)
            assert controller_metadata is not None
            controller_pipeline = get_controller_pipeline_metadata(controller_cls, inherit=True)

            for route_definition in iter_controller_routes(controller_cls):
                binding_plan = compile_parameter_bindings(controller_cls, route_definition)
                pipeline_metadata = merge_pipeline_metadata(
                    controller_pipeline or PipelineMetadata(),
                    get_handler_pipeline_metadata(route_definition.handler) or PipelineMetadata(),
                )
                _validate_pipeline_metadata(pipeline_metadata)

                route_path = _join_paths(controller_metadata.prefix, route_definition.route.path)
                route_key = (route_definition.route.method, route_path)
                route_owner = _handler_reference(controller_cls, route_definition.handler_name)
                previous_route_owner = seen_routes.get(route_key)
                if previous_route_owner is not None:
                    raise RouteDefinitionError(
                        f"Duplicate application route {route_definition.route.method} {route_path} "
                        f"declared by {previous_route_owner} and {route_owner}"
                    )

                seen_routes[route_key] = route_owner
                compiled_routes.append(
                    Route(
                        path=route_path,
                        endpoint=create_endpoint(
                            container,
                            node.module,
                            controller_cls,
                            route_definition,
                            binding_plan,
                            pipeline_metadata,
                        ),
                        methods=[route_definition.route.method],
                        name=route_owner,
                    )
                )

    return tuple(compiled_routes)


def create_endpoint(
    container: Container,
    module_cls: type[object],
    controller_cls: type[object],
    route_definition: ControllerRouteDefinition,
    binding_plan: HandlerBindingPlan,
    pipeline_metadata: PipelineMetadata,
) -> Endpoint:
    """Create the Starlette endpoint callable for one controller handler."""

    is_async_handler = inspect.iscoroutinefunction(route_definition.handler)

    async def endpoint(request: Request) -> Response:
        controller_instance = container.instantiate_class(
            controller_cls, module=module_cls, request=request
        )
        handler = getattr(controller_instance, route_definition.handler_name)
        request_context = RequestContext(
            request=request,
            module=module_cls,
            controller_type=controller_cls,
            controller=controller_instance,
            route=route_definition,
            container=container,
        )

        # Resolve filters first
        filters = _resolve_pipeline_components(
            pipeline_metadata.filters,
            expected_base_type=ExceptionFilter,
            container=container,
            module_cls=module_cls,
            component_kind="filter",
            request=request,
        )

        try:
            guards = _resolve_pipeline_components(
                pipeline_metadata.guards,
                expected_base_type=Guard,
                container=container,
                module_cls=module_cls,
                component_kind="guard",
                request=request,
            )
            pipes = _resolve_pipeline_components(
                pipeline_metadata.pipes,
                expected_base_type=Pipe,
                container=container,
                module_cls=module_cls,
                component_kind="pipe",
                request=request,
            )
            interceptors = _resolve_pipeline_components(
                pipeline_metadata.interceptors,
                expected_base_type=Interceptor,
                container=container,
                module_cls=module_cls,
                component_kind="interceptor",
                request=request,
            )

            await run_guards(request_context, guards)
            bound_parameters = await bind_handler_parameters(request, binding_plan)
            piped_parameters = await _apply_pipes(bound_parameters, request_context, pipes)
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

            result = await call_with_interceptors(handler_context, interceptors, final_handler)
        except ParameterBindingError as exc:
            filtered_result = await handle_exception(request_context, exc, filters)
            if filtered_result is not None:
                return coerce_response(filtered_result)
            return JSONResponse({"detail": str(exc)}, status_code=400)
        except GuardRejectedError as exc:
            filtered_result = await handle_exception(request_context, exc, filters)
            if filtered_result is not None:
                return coerce_response(filtered_result)
            return JSONResponse({"detail": str(exc)}, status_code=403)
        except Exception as exc:
            filtered_result = await handle_exception(request_context, exc, filters)
            if filtered_result is not None:
                return coerce_response(filtered_result)
            raise

        return coerce_response(result)

    endpoint.__name__ = route_definition.route.name
    return endpoint


def _handler_reference(controller_cls: type[object], handler_name: str) -> str:
    return f"{_qualname(controller_cls)}.{handler_name}"


def _validate_pipeline_metadata(pipeline_metadata: PipelineMetadata) -> None:
    _validate_pipeline_components(pipeline_metadata.guards, Guard, component_kind="guard")
    _validate_pipeline_components(pipeline_metadata.pipes, Pipe, component_kind="pipe")
    _validate_pipeline_components(
        pipeline_metadata.interceptors,
        Interceptor,
        component_kind="interceptor",
    )
    _validate_pipeline_components(
        pipeline_metadata.filters,
        ExceptionFilter,
        component_kind="filter",
    )


def _validate_pipeline_components(
    components: tuple[object, ...],
    expected_base_type: type[object],
    *,
    component_kind: str,
) -> None:
    for component in components:
        if isinstance(component, type):
            if not issubclass(component, expected_base_type):
                raise InvalidPipelineError(
                    f"{component_kind.capitalize()} {_qualname(component)} must inherit from "
                    f"{expected_base_type.__name__}"
                )
            continue

        if not isinstance(component, expected_base_type):
            raise InvalidPipelineError(
                f"{component_kind.capitalize()} {component!r} must be an instance of "
                f"{expected_base_type.__name__}"
            )


def _resolve_pipeline_components(
    components: tuple[object, ...],
    *,
    expected_base_type: type[ComponentT],
    container: Container,
    module_cls: type[object],
    component_kind: str,
    request: Request,
) -> tuple[ComponentT, ...]:
    resolved_components: list[ComponentT] = []

    for component in components:
        resolved_component = component
        if isinstance(component, type):
            component_type = cast(type[ComponentT], component)
            if getattr(component_type, BUSTAN_PROVIDER_ATTR, None) is not None:
                resolved_component = container.resolve(
                    component_type,
                    module=module_cls,
                    request=request,
                )
            else:
                try:
                    resolved_component = component_type()
                except TypeError as exc:
                    raise InvalidPipelineError(
                        f"{component_kind.capitalize()} {_qualname(component_type)} must be provided as "
                        "an instance, a no-argument class, or an injectable provider"
                    ) from exc

        if not isinstance(resolved_component, expected_base_type):
            raise InvalidPipelineError(
                f"Resolved {component_kind} {_qualname(type(resolved_component))} must inherit from "
                f"{expected_base_type.__name__}"
            )

        resolved_components.append(resolved_component)

    return tuple(resolved_components)


async def _apply_pipes(
    bound_parameters: tuple[BoundParameter, ...],
    request_context: RequestContext,
    pipes: tuple[Pipe, ...],
) -> tuple[BoundParameter, ...]:
    if not pipes:
        return bound_parameters

    transformed_parameters: list[BoundParameter] = []
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
