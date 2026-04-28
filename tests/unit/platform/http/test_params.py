"""Unit tests for request parameter compilation and binding."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Annotated, Mapping
from urllib.parse import urlencode

import anyio
import pytest
from starlette.requests import Request

from bustan import Body, Controller, Cookies, Get, Header, HostParam, Ip, Param, Post, Query
from bustan.core.errors import ParameterBindingError
from bustan.platform.http.metadata import iter_controller_routes
from bustan.platform.http.params import (
    ParameterSource,
    bind_handler_arguments,
    compile_parameter_bindings,
)


@dataclass(frozen=True, slots=True)
class CreateUserPayload:
    name: str
    admin: bool


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
