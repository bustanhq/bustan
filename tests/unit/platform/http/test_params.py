"""Unit tests for request parameter compilation and binding."""

from __future__ import annotations

import json
import inspect
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Annotated, Any, Mapping, cast
from urllib.parse import urlencode

import anyio
import pytest
from pydantic import BaseModel
from starlette.datastructures import FormData, Headers, QueryParams
from starlette.requests import Request

from bustan import (
    Body,
    Controller,
    Cookies,
    Get,
    Header,
    HostParam,
    Ip,
    Param,
    Post,
    Query,
    UploadedFile,
    UploadedFiles,
    create_param_decorator,
)
from bustan.core.errors import ParameterBindingError
from bustan.pipeline.context import ExecutionContext
from bustan.platform.http.abstractions import HttpRequest, StarletteHttpRequest
from bustan.platform.http.metadata import ControllerRouteDefinition, iter_controller_routes
from bustan.platform.http.params import (
    HandlerBindingPlan,
    ParameterBinding,
    ParameterBindingMode,
    ParameterSource,
    ValidationMode,
    _bind_parameter,
    _compile_parameter_source,
    _coerce_value,
    _extract_body_value,
    _extract_marker,
    _has_explicit_source,
    _infer_body_model,
    _MISSING,
    _NO_BODY,
    _query_value,
    _resolve_binding_mode,
    _resolve_validation_mode,
    _source_from_marker,
    _UNSET_BODY,
    bind_handler_arguments,
    compile_parameter_bindings,
)


@dataclass(frozen=True, slots=True)
class CreateUserPayload:
    name: str
    admin: bool


class UpdateUserPayload(BaseModel):
    name: str
    admin: bool


UnitCurrentRequestData = create_param_decorator(
    lambda data, ctx: ctx.get_handler().__name__
    if data is None
    else ctx.switch_to_http().get_request().headers[data],
    name="CurrentRequestData",
)

UnitCurrentRequestPath = create_param_decorator(
    lambda data, ctx: ctx.switch_to_http().get_request().path,
    name="CurrentRequestPath",
)


def test_bind_handler_arguments_injects_request_and_converts_path_and_query_values() -> None:
    @Controller("/users")
    class UsersController:
        @Get("/{user_id}")
        def read_user(
            self,
            request: Request,
            user_id: int,
            verbose: bool = False,
            page: int = 1,
        ) -> None:
            return None

    route_definition = iter_controller_routes(UsersController)[0]
    binding_plan = compile_parameter_bindings(UsersController, route_definition)
    request = _build_request(
        method="GET",
        path="/users/41",
        path_params={"user_id": "41"},
        query_params={"verbose": "true", "page": "2"},
    )

    positional_arguments, keyword_arguments = anyio.run(
        bind_handler_arguments, request, binding_plan
    )

    assert keyword_arguments == {}
    assert positional_arguments[0] is request
    assert positional_arguments[1:] == (41, True, 2)


def test_bind_handler_arguments_supports_adapter_neutral_http_request_annotations() -> None:
    @Controller("/users")
    class UsersController:
        @Get("/")
        def list_users(self, request: HttpRequest) -> None:
            return None

    route_definition = iter_controller_routes(UsersController)[0]
    binding_plan = compile_parameter_bindings(UsersController, route_definition)
    request = StarletteHttpRequest(_build_request(method="GET", path="/users"))

    positional_arguments, keyword_arguments = anyio.run(
        bind_handler_arguments, request, binding_plan
    )

    assert keyword_arguments == {}
    assert positional_arguments[0] is request


def test_bind_handler_arguments_binds_json_body_to_a_dataclass() -> None:
    @Controller("/users")
    class UsersController:
        @Post("/")
        def create_user(self, payload: CreateUserPayload) -> None:
            return None

    route_definition = iter_controller_routes(UsersController)[0]
    binding_plan = compile_parameter_bindings(UsersController, route_definition)
    request = _build_request(
        method="POST",
        path="/users",
        json_body={"name": "Ada", "admin": True},
    )

    positional_arguments, keyword_arguments = anyio.run(
        bind_handler_arguments, request, binding_plan
    )

    assert keyword_arguments == {}
    assert positional_arguments == (CreateUserPayload(name="Ada", admin=True),)


def test_bind_handler_arguments_rejects_invalid_query_values() -> None:
    @Controller("/users")
    class UsersController:
        @Get("/")
        def list_users(self, page: int) -> None:
            return None

    route_definition = iter_controller_routes(UsersController)[0]
    binding_plan = compile_parameter_bindings(UsersController, route_definition)
    request = _build_request(
        method="GET",
        path="/users",
        query_params={"page": "not-a-number"},
    )

    with pytest.raises(ParameterBindingError, match="query parameter 'page'"):
        anyio.run(bind_handler_arguments, request, binding_plan)


def test_bind_handler_arguments_supports_list_query_values_and_keyword_only_parameters() -> None:
    @Controller("/users")
    class UsersController:
        @Get("/")
        def list_users(self, page: int, *, tags: list[int]) -> None:
            return None

    route_definition = iter_controller_routes(UsersController)[0]
    binding_plan = compile_parameter_bindings(UsersController, route_definition)
    request = _build_request(
        method="GET",
        path="/users",
        query_params={"page": "2", "tags": ["1", "3", "5"]},
    )

    positional_arguments, keyword_arguments = anyio.run(
        bind_handler_arguments, request, binding_plan
    )

    assert positional_arguments == (2,)
    assert keyword_arguments == {"tags": [1, 3, 5]}


def test_bind_handler_arguments_uses_scalar_request_bodies_for_single_parameters() -> None:
    @Controller("/counters")
    class CountersController:
        @Post("/")
        def set_count(self, count: int) -> None:
            return None

    route_definition = iter_controller_routes(CountersController)[0]
    binding_plan = compile_parameter_bindings(CountersController, route_definition)
    request = _build_request(method="POST", path="/counters", json_body=5)

    positional_arguments, keyword_arguments = anyio.run(
        bind_handler_arguments, request, binding_plan
    )

    assert positional_arguments == (5,)
    assert keyword_arguments == {}


def test_bind_handler_arguments_allows_null_for_optional_body_parameters() -> None:
    @Controller("/counters")
    class CountersController:
        @Post("/")
        def set_count(self, count: int | None) -> None:
            return None

    route_definition = iter_controller_routes(CountersController)[0]
    binding_plan = compile_parameter_bindings(CountersController, route_definition)
    request = _build_request(method="POST", path="/counters", raw_body=b"null")

    positional_arguments, keyword_arguments = anyio.run(
        bind_handler_arguments, request, binding_plan
    )

    assert positional_arguments == (None,)
    assert keyword_arguments == {}


def test_bind_handler_arguments_requires_json_objects_for_multiple_body_fields() -> None:
    @Controller("/users")
    class UsersController:
        @Post("/")
        def create_user(self, name: str, admin: bool) -> None:
            return None

    route_definition = iter_controller_routes(UsersController)[0]
    binding_plan = compile_parameter_bindings(UsersController, route_definition)
    request = _build_request(method="POST", path="/users", raw_body=b'"Ada"')

    with pytest.raises(ParameterBindingError, match="requires a JSON object"):
        anyio.run(bind_handler_arguments, request, binding_plan)


def test_bind_handler_arguments_uses_defaults_when_request_data_is_missing() -> None:
    @Controller("/users")
    class UsersController:
        @Get("/")
        def list_users(self, page: int = 7) -> None:
            return None

    route_definition = iter_controller_routes(UsersController)[0]
    binding_plan = compile_parameter_bindings(UsersController, route_definition)
    request = _build_request(method="GET", path="/users")

    positional_arguments, keyword_arguments = anyio.run(
        bind_handler_arguments, request, binding_plan
    )

    assert positional_arguments == (7,)
    assert keyword_arguments == {}


def test_bind_handler_arguments_reports_invalid_json_request_bodies() -> None:
    @Controller("/users")
    class UsersController:
        @Post("/")
        def create_user(self, payload: CreateUserPayload) -> None:
            return None

    route_definition = iter_controller_routes(UsersController)[0]
    binding_plan = compile_parameter_bindings(UsersController, route_definition)
    request = _build_request(method="POST", path="/users", raw_body=b"{not-json}")

    with pytest.raises(ParameterBindingError, match="Request body must contain valid JSON"):
        anyio.run(bind_handler_arguments, request, binding_plan)


def test_bind_handler_arguments_rejects_boolean_json_values_for_int_parameters() -> None:
    @Controller("/counters")
    class CountersController:
        @Post("/")
        def set_count(self, count: int) -> None:
            return None

    route_definition = iter_controller_routes(CountersController)[0]
    binding_plan = compile_parameter_bindings(CountersController, route_definition)
    request = _build_request(method="POST", path="/counters", json_body=True)

    with pytest.raises(ParameterBindingError, match="request body 'count' to int"):
        anyio.run(bind_handler_arguments, request, binding_plan)


def test_compile_parameter_bindings_resolves_string_annotations_and_ignores_return_annotations() -> (
    None
):
    @Controller("/users")
    class UsersController:
        @Post("/")
        def create_user(self, payload: CreateUserPayload) -> None:
            return None

    UsersController.create_user.__annotations__["return"] = "MissingReturnType"

    route_definition = iter_controller_routes(UsersController)[0]

    binding_plan = compile_parameter_bindings(UsersController, route_definition)

    assert binding_plan.parameters[0].annotation is CreateUserPayload


def test_compile_parameter_bindings_rejects_unresolvable_parameter_annotations() -> None:
    @Controller("/users")
    class UsersController:
        @Post("/")
        def create_user(self, payload: object) -> None:
            return None

    UsersController.create_user.__annotations__["payload"] = "MissingPayload"

    route_definition = iter_controller_routes(UsersController)[0]

    with pytest.raises(ParameterBindingError, match="Could not resolve type hints"):
        compile_parameter_bindings(UsersController, route_definition)


def test_bind_handler_arguments_supports_explicit_annotated_markers() -> None:
    @Controller("/users")
    class UsersController:
        @Get("/{user_id}")
        def read_user(
            self,
            user_id: Annotated[int, Param],
            search: Annotated[str, Query("q")],
            token: Annotated[str, Header("X-API-Token")],
            payload: Annotated[CreateUserPayload, Body],
        ) -> None:
            return None

    route_definition = iter_controller_routes(UsersController)[0]
    binding_plan = compile_parameter_bindings(UsersController, route_definition)

    # Verify compilation
    param_bindings = {b.name: b for b in binding_plan.parameters}
    assert param_bindings["user_id"].source == ParameterSource.PATH
    assert param_bindings["search"].source == ParameterSource.QUERY
    assert param_bindings["search"].alias == "q"
    assert param_bindings["token"].source == ParameterSource.HEADER
    assert param_bindings["token"].alias == "X-API-Token"
    assert param_bindings["payload"].source == ParameterSource.BODY

    request = _build_request(
        method="POST",
        path="/users/42",
        path_params={"user_id": "42"},
        query_params={"q": "Ada"},
        headers=[(b"x-api-token", b"secret")],
        json_body={"name": "Ada", "admin": True},
    )

    args, kwargs = anyio.run(bind_handler_arguments, request, binding_plan)

    assert args == (42, "Ada", "secret", CreateUserPayload(name="Ada", admin=True))


def test_bind_handler_arguments_supports_header_underscore_to_hyphen_conversion() -> None:
    @Controller("/")
    class TestController:
        @Get("/")
        def index(self, x_request_id: Annotated[str, Header]) -> None:
            return None

    route_definition = iter_controller_routes(TestController)[0]
    binding_plan = compile_parameter_bindings(TestController, route_definition)
    request = _build_request(
        method="GET",
        path="/",
        headers=[(b"x-request-id", b"id-123")],
    )

    args, kwargs = anyio.run(bind_handler_arguments, request, binding_plan)
    assert args == ("id-123",)


def test_bind_handler_arguments_supports_execution_context_backed_custom_param_decorators() -> None:
    @Controller("/")
    class TestController:
        @Get("/")
        def index(
            self,
            handler_name: Annotated[str, UnitCurrentRequestData],
            request_id: Annotated[str, UnitCurrentRequestData("x-request-id")],
        ) -> None:
            return None

    route_definition = iter_controller_routes(TestController)[0]
    binding_plan = compile_parameter_bindings(TestController, route_definition)
    handler_binding, request_id_binding = binding_plan.parameters

    assert handler_binding.source is ParameterSource.CUSTOM
    assert callable(handler_binding.custom_resolver)
    assert handler_binding.custom_data is None
    assert request_id_binding.source is ParameterSource.CUSTOM
    assert request_id_binding.custom_data == "x-request-id"

    request = _build_request(
        method="GET",
        path="/",
        headers=[(b"x-request-id", b"id-123")],
    )
    context = _execution_context(request, TestController, route_definition)

    args, kwargs = anyio.run(bind_handler_arguments, request, binding_plan, context)

    assert kwargs == {}
    assert args == ("index", "id-123")


def test_bind_handler_arguments_requires_execution_context_for_custom_param_decorators() -> None:
    @Controller("/")
    class TestController:
        @Get("/")
        def index(self, path: Annotated[str, UnitCurrentRequestPath]) -> None:
            return None

    route_definition = iter_controller_routes(TestController)[0]
    binding_plan = compile_parameter_bindings(TestController, route_definition)
    request = _build_request(method="GET", path="/")

    with pytest.raises(ParameterBindingError, match="execution context"):
        anyio.run(bind_handler_arguments, request, binding_plan)


def test_bind_handler_arguments_supports_cookie_ip_and_host_markers() -> None:
    @Controller("/")
    class TestController:
        @Get("/")
        def index(
            self,
            session_id: Annotated[str | None, Cookies("session")],
            host: Annotated[str | None, HostParam],
            ip_address: Annotated[str | None, Ip],
        ) -> None:
            return None

    route_definition = iter_controller_routes(TestController)[0]
    binding_plan = compile_parameter_bindings(TestController, route_definition)
    request = _build_request(
        method="GET",
        path="/",
        headers=[
            (b"cookie", b"session=abc123"),
            (b"host", b"api.example.test"),
        ],
    )

    args, kwargs = anyio.run(bind_handler_arguments, request, binding_plan)

    assert kwargs == {}
    assert args == ("abc123", "api.example.test", "testclient")


def test_bind_handler_arguments_host_param_honors_alias_header() -> None:
    @Controller("/")
    class TestController:
        @Get("/")
        def index(
            self,
            forwarded_host: Annotated[str | None, HostParam("x-forwarded-host")],
        ) -> None:
            return None

    route_definition = iter_controller_routes(TestController)[0]
    binding_plan = compile_parameter_bindings(TestController, route_definition)
    request = _build_request(
        method="GET",
        path="/",
        headers=[(b"x-forwarded-host", b"real.example.com")],
    )

    args, kwargs = anyio.run(bind_handler_arguments, request, binding_plan)

    assert args == ("real.example.com",)


def test_bind_handler_arguments_cookie_mapping_annotation_returns_all_cookies() -> None:
    @Controller("/")
    class TestController:
        @Get("/")
        def index(
            self,
            all_cookies: Annotated[dict[str, str], Cookies],
            all_cookies_mapping: Annotated[Mapping[str, str], Cookies],
        ) -> None:
            return None

    route_definition = iter_controller_routes(TestController)[0]
    binding_plan = compile_parameter_bindings(TestController, route_definition)
    request = _build_request(
        method="GET",
        path="/",
        headers=[(b"cookie", b"a=1; b=2")],
    )

    args, kwargs = anyio.run(bind_handler_arguments, request, binding_plan)

    assert args == ({"a": "1", "b": "2"}, {"a": "1", "b": "2"})


def test_bind_handler_arguments_reports_missing_required_path_parameters() -> None:
    @Controller("/users")
    class UsersController:
        @Get("/{user_id}")
        def read_user(self, user_id: int) -> None:
            return None

    route_definition = iter_controller_routes(UsersController)[0]
    binding_plan = compile_parameter_bindings(UsersController, route_definition)
    request = _build_request(method="GET", path="/users")

    with pytest.raises(ParameterBindingError, match="Missing required path parameter") as exc_info:
        anyio.run(bind_handler_arguments, request, binding_plan)

    assert exc_info.value.field == "user_id"
    assert exc_info.value.source == "path parameter"


def test_bind_parameter_prefers_query_values_over_body_for_inferred_bindings() -> None:
    binding_plan = _binding_plan(
        ParameterBinding(
            name="count",
            kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
            source=ParameterSource.INFERRED,
            annotation=int,
            has_default=False,
        ),
        inferred_parameter_names=("count",),
    )
    request = _request_stub(
        query_params={"count": "3"},
        body=b"5",
        json_value=5,
    )

    value, request_body = anyio.run(
        _bind_parameter,
        request,
        binding_plan,
        binding_plan.parameters[0],
        _UNSET_BODY,
    )

    assert value == 3
    assert request_body is _UNSET_BODY


def test_bind_handler_arguments_reports_missing_required_headers() -> None:
    @Controller("/")
    class TestController:
        @Get("/")
        def index(self, token: Annotated[str, Header("X-API-Token")]) -> None:
            return None

    route_definition = iter_controller_routes(TestController)[0]
    binding_plan = compile_parameter_bindings(TestController, route_definition)
    request = _build_request(method="GET", path="/")

    with pytest.raises(ParameterBindingError, match="Missing required header") as exc_info:
        anyio.run(bind_handler_arguments, request, binding_plan)

    assert exc_info.value.field == "token"
    assert exc_info.value.source == "header"


def test_bind_handler_arguments_supports_uploaded_file_and_files_markers() -> None:
    @Controller("/uploads")
    class UploadsController:
        @Post("/")
        def upload(
            self,
            avatar: Annotated[object, UploadedFile("avatar")],
            attachments: Annotated[list[object], UploadedFiles("attachments")],
        ) -> None:
            return None

    route_definition = iter_controller_routes(UploadsController)[0]
    binding_plan = compile_parameter_bindings(UploadsController, route_definition)
    request = _request_stub(
        form_data=FormData(
            [
                ("avatar", cast(Any, object())),
                ("attachments", "one"),
                ("attachments", "two"),
            ]
        )
    )

    avatar, request_body = anyio.run(
        _bind_parameter,
        request,
        binding_plan,
        binding_plan.parameters[0],
        _UNSET_BODY,
    )
    attachments, request_body = anyio.run(
        _bind_parameter,
        request,
        binding_plan,
        binding_plan.parameters[1],
        request_body,
    )

    assert avatar is not None
    assert attachments == ["one", "two"]


def test_bind_parameter_returns_none_or_defaults_for_optional_transport_values() -> None:
    request = _request_stub(client=None)
    binding_plan = _binding_plan(
        ParameterBinding(
            name="session_id",
            kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
            source=ParameterSource.COOKIE,
            annotation=str | None,
            has_default=False,
            alias="session",
        ),
        ParameterBinding(
            name="ip_address",
            kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
            source=ParameterSource.IP,
            annotation=str | None,
            has_default=True,
            default="127.0.0.1",
        ),
        ParameterBinding(
            name="host",
            kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
            source=ParameterSource.HOST,
            annotation=str | None,
            has_default=False,
        ),
    )

    cookie_value, request_body = anyio.run(
        _bind_parameter,
        request,
        binding_plan,
        binding_plan.parameters[0],
        _UNSET_BODY,
    )
    ip_value, request_body = anyio.run(
        _bind_parameter,
        request,
        binding_plan,
        binding_plan.parameters[1],
        request_body,
    )
    host_value, request_body = anyio.run(
        _bind_parameter,
        request,
        binding_plan,
        binding_plan.parameters[2],
        request_body,
    )

    assert cookie_value is None
    assert ip_value == "127.0.0.1"
    assert host_value is None


def test_bind_parameter_uses_default_for_missing_body_and_reports_missing_inferred_values() -> None:
    binding_plan = _binding_plan(
        ParameterBinding(
            name="payload",
            kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
            source=ParameterSource.BODY,
            annotation=int,
            has_default=True,
            default=7,
        ),
        ParameterBinding(
            name="count",
            kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
            source=ParameterSource.INFERRED,
            annotation=int,
            has_default=False,
        ),
        inferred_parameter_names=("count",),
    )
    empty_request = _request_stub(body=b"", json_value=None)

    payload, request_body = anyio.run(
        _bind_parameter,
        empty_request,
        binding_plan,
        binding_plan.parameters[0],
        _UNSET_BODY,
    )

    assert payload == 7

    with pytest.raises(ParameterBindingError, match="Missing required parameter 'count'"):
        anyio.run(
            _bind_parameter,
            empty_request,
            binding_plan,
            binding_plan.parameters[1],
            request_body,
        )


def test_binding_mode_and_validation_mode_helpers_reject_invalid_values() -> None:
    assert _resolve_binding_mode("infer") is ParameterBindingMode.INFER
    assert _resolve_validation_mode("auto") is ValidationMode.AUTO

    with pytest.raises(ParameterBindingError, match="Unsupported parameter binding mode"):
        _resolve_binding_mode("broken")

    with pytest.raises(ParameterBindingError, match="Unsupported validation mode"):
        _resolve_validation_mode("broken")


def test_infer_body_model_and_marker_helpers_cover_edge_cases() -> None:
    inferred_binding = ParameterBinding(
        name="payload",
        kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
        source=ParameterSource.BODY,
        annotation=UpdateUserPayload,
        has_default=False,
    )
    aliased_binding = ParameterBinding(
        name="payload",
        kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
        source=ParameterSource.BODY,
        annotation=UpdateUserPayload,
        has_default=False,
        alias="body",
    )
    builtin_binding = ParameterBinding(
        name="payload",
        kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
        source=ParameterSource.BODY,
        annotation=dict,
        has_default=False,
    )

    CurrentPath = create_param_decorator(lambda data, ctx: ctx.switch_to_http().get_request().path)

    assert _infer_body_model((inferred_binding,), ("payload",)) is UpdateUserPayload
    assert _infer_body_model((aliased_binding,), ()) is None
    assert _infer_body_model((builtin_binding,), ("payload",)) is None
    assert _source_from_marker(CurrentPath) is ParameterSource.CUSTOM
    assert _source_from_marker(CurrentPath("path")) is ParameterSource.CUSTOM
    assert _source_from_marker(object()) is ParameterSource.INFERRED


def test_extract_body_value_handles_single_and_multiple_inferred_bindings() -> None:
    single_binding = ParameterBinding(
        name="payload",
        kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
        source=ParameterSource.INFERRED,
        annotation=dict[str, object],
        has_default=False,
    )
    single_plan = _binding_plan(single_binding, inferred_parameter_names=("payload",))

    assert _extract_body_value(single_plan, single_binding, {"name": "Ada"}) == {"name": "Ada"}

    multiple_plan = _binding_plan(
        ParameterBinding(
            name="name",
            kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
            source=ParameterSource.INFERRED,
            annotation=str,
            has_default=False,
        ),
        ParameterBinding(
            name="admin",
            kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
            source=ParameterSource.INFERRED,
            annotation=bool,
            has_default=False,
        ),
        inferred_parameter_names=("name", "admin"),
    )

    with pytest.raises(ParameterBindingError, match="requires a JSON object"):
        _extract_body_value(multiple_plan, multiple_plan.parameters[0], "Ada")


def test_coerce_value_covers_container_pydantic_and_scalar_error_paths() -> None:
    assert _coerce_value(
        {"name": "Ada"},
        annotation=UpdateUserPayload,
        parameter_name="payload",
        source_description="request body",
    ) == {"name": "Ada"}

    with pytest.raises(ParameterBindingError, match="to list"):
        _coerce_value(
            "not-a-list",
            annotation=list[int],
            parameter_name="tags",
            source_description="query parameter",
        )

    with pytest.raises(ParameterBindingError, match="to dict"):
        _coerce_value(
            "not-a-dict",
            annotation=dict,
            parameter_name="payload",
            source_description="request body",
        )

    with pytest.raises(ParameterBindingError, match="to bool"):
        _coerce_value(
            "sometimes",
            annotation=bool,
            parameter_name="enabled",
            source_description="query parameter",
        )

    with pytest.raises(ParameterBindingError, match="to int"):
        _coerce_value(
            True,
            annotation=int,
            parameter_name="count",
            source_description="request body",
        )

    with pytest.raises(ParameterBindingError, match="to float"):
        _coerce_value(
            object(),
            annotation=float,
            parameter_name="count",
            source_description="request body",
        )

    class BrokenType:
        def __init__(self, value: object) -> None:
            raise ValueError("boom")

    with pytest.raises(ParameterBindingError, match="boom"):
        _coerce_value(
            "value",
            annotation=BrokenType,
            parameter_name="broken",
            source_description="query parameter",
        )


def test_compile_parameter_source_covers_explicit_safe_unsafe_and_strict_modes() -> None:
    class StubController:
        pass

    parameter = inspect.signature(lambda payload: None).parameters["payload"]

    assert _compile_parameter_source(
        controller_cls=StubController,
        handler_name="create",
        parameter=parameter,
        annotation=int,
        marker=None,
        path_parameter_names=frozenset(),
        method="GET",
        binding_mode=ParameterBindingMode.EXPLICIT,
        unresolved_parameter_count=2,
    ) == (ParameterSource.QUERY, False)

    assert _compile_parameter_source(
        controller_cls=StubController,
        handler_name="create",
        parameter=parameter,
        annotation=int,
        marker=None,
        path_parameter_names=frozenset(),
        method="POST",
        binding_mode=ParameterBindingMode.EXPLICIT,
        unresolved_parameter_count=1,
    ) == (ParameterSource.BODY, True)

    with pytest.raises(ParameterBindingError, match="ambiguous in explicit mode"):
        _compile_parameter_source(
            controller_cls=StubController,
            handler_name="create",
            parameter=parameter,
            annotation=int,
            marker=None,
            path_parameter_names=frozenset(),
            method="POST",
            binding_mode=ParameterBindingMode.EXPLICIT,
            unresolved_parameter_count=2,
        )

    with pytest.raises(ParameterBindingError, match="strict mode"):
        _compile_parameter_source(
            controller_cls=StubController,
            handler_name="create",
            parameter=parameter,
            annotation=int,
            marker=None,
            path_parameter_names=frozenset(),
            method="POST",
            binding_mode=ParameterBindingMode.STRICT,
            unresolved_parameter_count=1,
        )


def test_bind_parameter_covers_cookie_mapping_missing_uploads_and_default_query_lists() -> None:
    binding_plan = _binding_plan(
        ParameterBinding(
            name="all_cookies",
            kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
            source=ParameterSource.COOKIE,
            annotation=Mapping[str, str],
            has_default=False,
        ),
        ParameterBinding(
            name="avatar",
            kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
            source=ParameterSource.FILE,
            annotation=object,
            has_default=True,
            default="fallback",
            alias="avatar",
        ),
        ParameterBinding(
            name="attachments",
            kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
            source=ParameterSource.FILES,
            annotation=list[object],
            has_default=False,
            alias="attachments",
        ),
        ParameterBinding(
            name="tags",
            kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
            source=ParameterSource.QUERY,
            annotation=list[int],
            has_default=True,
            default=[7],
        ),
    )
    request = _request_stub(cookies={"session": "abc123"}, form_data=FormData())

    all_cookies, request_body = anyio.run(
        _bind_parameter,
        request,
        binding_plan,
        binding_plan.parameters[0],
        _UNSET_BODY,
    )
    avatar, request_body = anyio.run(
        _bind_parameter,
        request,
        binding_plan,
        binding_plan.parameters[1],
        request_body,
    )
    attachments, request_body = anyio.run(
        _bind_parameter,
        request,
        binding_plan,
        binding_plan.parameters[2],
        request_body,
    )
    tags, _request_body = anyio.run(
        _bind_parameter,
        request,
        binding_plan,
        binding_plan.parameters[3],
        request_body,
    )

    assert all_cookies == {"session": "abc123"}
    assert avatar == "fallback"
    assert attachments == []
    assert tags == [7]


def test_marker_and_explicit_source_helpers_cover_supported_markers() -> None:
    signature = inspect.signature(lambda request, user_id, search: None)
    annotated, marker = _extract_marker(Annotated[str, Query("search")])
    CurrentUser = create_param_decorator(lambda data, ctx: data)

    assert annotated is str
    assert _source_from_marker(Body) is ParameterSource.BODY
    assert _source_from_marker(Query("q")) is ParameterSource.QUERY
    assert _source_from_marker(Param) is ParameterSource.PATH
    assert _source_from_marker(Header("X-Token")) is ParameterSource.HEADER
    assert _source_from_marker(Cookies("session")) is ParameterSource.COOKIE
    assert _source_from_marker(Ip) is ParameterSource.IP
    assert _source_from_marker(HostParam("x-forwarded-host")) is ParameterSource.HOST
    assert _source_from_marker(UploadedFile("avatar")) is ParameterSource.FILE
    assert _source_from_marker(UploadedFiles("attachments")) is ParameterSource.FILES
    assert _source_from_marker(CurrentUser) is ParameterSource.CUSTOM
    assert _source_from_marker(marker) is ParameterSource.QUERY

    assert _has_explicit_source(
        parameter=signature.parameters["request"],
        annotation=Request,
        path_parameter_names=frozenset(),
    ) is True
    assert _has_explicit_source(
        parameter=signature.parameters["user_id"],
        annotation=int,
        path_parameter_names=frozenset({"user_id"}),
    ) is True
    assert _has_explicit_source(
        parameter=signature.parameters["search"],
        annotation=Annotated[str, Query("search")],
        path_parameter_names=frozenset(),
    ) is True


def test_query_and_coerce_helpers_cover_missing_union_and_success_paths() -> None:
    @dataclass(frozen=True, slots=True)
    class Payload:
        name: str

    query_binding = ParameterBinding(
        name="tags",
        kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
        source=ParameterSource.QUERY,
        annotation=list[int],
        has_default=False,
    )
    request = _request_stub(query_params=[("tags", "1"), ("tags", "2")])

    assert _query_value(cast(HttpRequest, request), query_binding) == ["1", "2"]
    assert _query_value(cast(HttpRequest, _request_stub()), query_binding) is _MISSING

    inferred_binding = ParameterBinding(
        name="payload",
        kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
        source=ParameterSource.INFERRED,
        annotation=dict[str, object],
        has_default=False,
    )
    assert _extract_body_value(
        _binding_plan(inferred_binding, inferred_parameter_names=("payload",)),
        inferred_binding,
        _NO_BODY,
    ) is _MISSING

    payload = Payload(name="Ada")
    assert _coerce_value(
        payload,
        annotation=Payload,
        parameter_name="payload",
        source_description="request body",
    ) is payload
    assert _coerce_value(
        None,
        annotation=int | None,
        parameter_name="count",
        source_description="query parameter",
    ) is None
    assert _coerce_value(
        b"4",
        annotation=int,
        parameter_name="count",
        source_description="query parameter",
    ) == 4
    assert _coerce_value(
        5,
        annotation=float,
        parameter_name="ratio",
        source_description="query parameter",
    ) == 5.0
    assert _coerce_value(
        1.5,
        annotation=str,
        parameter_name="text",
        source_description="query parameter",
    ) == "1.5"
    assert _coerce_value(
        ["1", "2"],
        annotation=list[int],
        parameter_name="tags",
        source_description="query parameter",
    ) == [1, 2]


def _build_request(
    *,
    method: str,
    path: str,
    path_params: dict[str, object] | None = None,
    query_params: dict[str, object] | None = None,
    headers: list[tuple[bytes, bytes]] | None = None,
    json_body: object | None = None,
    raw_body: bytes | None = None,
) -> Request:
    """Construct a Request object with optional path, query, and JSON body data."""

    body_bytes = b""
    request_headers = list(headers or [])
    if not any(name.lower() == b"host" for name, _value in request_headers):
        request_headers.insert(0, (b"host", b"testserver"))

    if json_body is not None:
        body_bytes = json.dumps(json_body).encode("utf-8")
        request_headers.append((b"content-type", b"application/json"))
    elif raw_body is not None:
        body_bytes = raw_body
        request_headers.append((b"content-type", b"application/json"))

    query_string = urlencode(query_params or {}, doseq=True).encode("utf-8")
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": query_string,
        "headers": request_headers,
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
        "path_params": path_params or {},
    }

    request_sent = False

    async def receive() -> dict[str, object]:
        nonlocal request_sent
        if request_sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        request_sent = True
        return {"type": "http.request", "body": body_bytes, "more_body": False}

    return Request(scope, receive)


def _binding_plan(
    *bindings: ParameterBinding,
    inferred_parameter_names: tuple[str, ...] = (),
) -> HandlerBindingPlan:
    class StubController:
        pass

    return HandlerBindingPlan(
        controller=StubController,
        handler_name="handler",
        parameters=bindings,
        inferred_parameter_names=inferred_parameter_names,
    )


def _execution_context(
    request: Request,
    controller_cls: type[object],
    route_definition: ControllerRouteDefinition,
) -> ExecutionContext:
    controller = controller_cls()
    return ExecutionContext.create_http(
        request=request,
        response=None,
        handler=getattr(controller, route_definition.handler_name),
        controller_cls=controller_cls,
        module=controller_cls,
        controller=controller,
        container=cast(Any, object()),
        route=route_definition,
    )


class _RequestStub:
    def __init__(
        self,
        *,
        path_params: dict[str, str] | None = None,
        query_params: dict[str, object] | list[tuple[str, object]] | None = None,
        headers: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
        client: Any = None,
        body: bytes = b"",
        json_value: object = None,
        form_data: FormData | None = None,
    ) -> None:
        self.path_params = path_params or {}
        self.query_params = QueryParams(query_params or [])
        self.headers = Headers(headers or {})
        self.cookies = cookies or {}
        self.client = client
        self.state = SimpleNamespace()
        self._body = body
        self._json_value = json_value
        self._form_data = form_data or FormData()

    async def body(self) -> bytes:
        return self._body

    async def json(self) -> object:
        if isinstance(self._json_value, Exception):
            raise self._json_value
        return self._json_value

    async def form(self) -> FormData:
        return self._form_data


def _request_stub(
    *,
    path_params: dict[str, str] | None = None,
    query_params: dict[str, object] | list[tuple[str, object]] | None = None,
    headers: dict[str, str] | None = None,
    cookies: dict[str, str] | None = None,
    client: Any = SimpleNamespace(host="testclient", port=50000),
    body: bytes = b"",
    json_value: object = None,
    form_data: FormData | None = None,
) -> _RequestStub:
    return _RequestStub(
        path_params=path_params,
        query_params=query_params,
        headers=headers,
        cookies=cookies,
        client=client,
        body=body,
        json_value=json_value,
        form_data=form_data,
    )
