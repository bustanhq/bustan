"""Unit tests for the public execution context API."""

from __future__ import annotations

from typing import Any, cast

from starlette.requests import Request

from bustan.common.types import RouteMetadata
from bustan.core.module.dynamic import ModuleInstanceKey
from bustan.pipeline.context import ArgumentsHost, ExecutionContext, HandlerContext, ParameterContext, RequestContext
from bustan.platform.http.metadata import ControllerRouteDefinition


def test_execution_context_exposes_http_arguments_in_stable_order() -> None:
    request = _build_request("/")
    response = object()

    class UsersController:
        def list_users(self) -> None:
            return None

    controller = UsersController()
    context = ExecutionContext.create_http(
        request=request,
        response=response,
        handler=controller.list_users,
        controller_cls=UsersController,
        module=UsersController,
        controller=controller,
        container=cast(Any, object()),
    )

    assert context.get_args() == (request, response)
    assert context.get_arg_by_index(0) is request
    assert context.get_arg_by_index(1) is response
    assert context.switch_to_http().get_request() is request
    assert context.switch_to_http().get_response() is response


def test_execution_context_exposes_handler_and_controller_metadata() -> None:
    request = _build_request("/")

    class UsersController:
        def list_users(self) -> None:
            return None

    controller = UsersController()
    context = ExecutionContext.create_http(
        request=request,
        response=None,
        handler=controller.list_users,
        controller_cls=UsersController,
        module=UsersController,
        controller=controller,
        container=cast(Any, object()),
    )

    assert context.get_handler() == controller.list_users
    assert context.get_class() is UsersController
    assert context.route_contract is None
    assert context.policy_plan is None


def test_context_helpers_cover_remaining_http_and_metadata_accessors() -> None:
    host = ArgumentsHost(("request", "response", "next"))
    assert host.get_arg_by_index(-1) is None
    assert host.get_arg_by_index(3) is None
    assert host.get_type() == "http"
    assert host.switch_to_http().get_next() == "next"

    request = _build_request("/")
    request.state.principal = "user-1"

    class UsersController:
        def list_users(self) -> None:
            return None

    controller = UsersController()
    route = ControllerRouteDefinition(
        handler_name="list_users",
        handler=UsersController.list_users,
        route=RouteMetadata(method="GET", path="/", name="list_users"),
    )
    request_context = RequestContext(
        request=request,
        module=ModuleInstanceKey(module=UsersController, instance_id="test"),
        controller_type=UsersController,
        controller=controller,
        route=route,
        container=cast(Any, object()),
    )

    assert request_context.request.path == "/"
    assert request_context.route is route
    assert request_context.get_module() == request_context.module
    assert request_context.get_principal() == "user-1"

    parameter_context = ParameterContext(
        request_context=request_context,
        name="payload",
        source="body",
        annotation=str,
        value=None,
    )
    handler_context = HandlerContext(
        request_context=request_context,
        arguments=(1,),
        keyword_arguments={"enabled": True},
    )

    assert parameter_context.execution_context is request_context
    assert parameter_context.metatype is str
    assert HandlerContext(
        request_context=request_context,
        arguments=(),
        keyword_arguments={},
    ).execution_context is request_context
    assert handler_context.execution_context is request_context
    assert ParameterContext(
        request_context=request_context,
        name="payload",
        source="body",
        annotation="Payload",
        value=None,
    ).metatype is None


def test_execution_context_properties_handle_missing_request_values() -> None:
    class UsersController:
        def list_users(self) -> None:
            return None

    controller = UsersController()
    context = ExecutionContext.create_http(
        request=None,
        response="response",
        handler=controller.list_users,
        controller_cls=UsersController,
        module=UsersController,
        controller=controller,
        container=cast(Any, object()),
    )

    assert context.get_principal() is None
    assert context.request is None
    assert context.response == "response"
    assert context.controller_type is UsersController
    assert context.controller is controller


def test_execution_context_parameter_accessors_cover_default_and_compatibility_paths() -> None:
    request = _build_request("/")

    class UsersController:
        def list_users(self) -> None:
            return None

    controller = UsersController()
    context = ExecutionContext.create_http(
        request=request,
        response=None,
        handler=controller.list_users,
        controller_cls=UsersController,
        module=UsersController,
        controller=controller,
        container=cast(Any, object()),
    )

    assert context.with_parameter_value("ignored") is context
    assert context.parameter_name is None
    assert context.parameter_source is None
    assert context.parameter_annotation is None
    assert context.parameter_value is None
    assert context.source is None
    assert context.annotation is None
    assert context.value is None
    assert context.validation_mode == "auto"
    assert context.validate_custom_decorators is False
    assert context.execution_context is context

    parameter_context = ParameterContext(
        request_context=context,
        name="payload",
        source="body",
        annotation=int,
        value=1,
    )

    updated_context = parameter_context.with_parameter_value(2)

    assert parameter_context.parameter_name == "payload"
    assert parameter_context.parameter_source == "body"
    assert parameter_context.parameter_annotation is int
    assert parameter_context.parameter_value == 1
    assert updated_context.value == 2
    assert updated_context.parameter_value == 2


def _build_request(path: str) -> Request:
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": b"",
        "headers": [(b"host", b"testserver")],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
        "path_params": {},
    }

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(scope, receive)
