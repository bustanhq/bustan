"""Integration tests for route registration and request binding."""

from __future__ import annotations
from collections.abc import Iterator
from typing import Any, cast

from dataclasses import dataclass
from pathlib import Path

from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from starlette.testclient import TestClient

from bustan import Controller, create_app, Get, Injectable, Module, Post, Scope
from bustan.platform.http.abstractions import HttpRequest, HttpResponse


@dataclass(frozen=True, slots=True)
class CreateUserPayload:
    name: str
    admin: bool


def test_create_app_registers_http_routes_and_coerces_common_return_types() -> None:
    @dataclass(frozen=True, slots=True)
    class StatusPayload:
        status: str

    @Injectable
    class GreetingService:
        pass

    @Controller("/greetings")
    class GreetingController:
        def __init__(self, greeting_service: GreetingService) -> None:
            self.greeting_service = greeting_service

        @Get("/dict")
        def read_dict(self) -> dict[str, str]:
            return {"message": "hello"}

        @Get("/list")
        def read_list(self) -> list[str]:
            return ["hello", "world"]

        @Get("/dataclass")
        def read_dataclass(self) -> StatusPayload:
            return StatusPayload(status="ok")

        @Get("/response")
        def read_response(self) -> PlainTextResponse:
            return PlainTextResponse("plain", status_code=202)

        @Get("/http-response")
        def read_http_response(self) -> HttpResponse:
            return HttpResponse.json({"message": "wrapped"}, status_code=203)

        @Get("/none")
        def read_none(self) -> None:
            return None

    @Module(
        controllers=[GreetingController], providers=[GreetingService], exports=[GreetingService]
    )
    class AppModule:
        pass

    with TestClient(cast(Any, create_app(AppModule))) as client:
        dict_response = client.get("/greetings/dict")
        list_response = client.get("/greetings/list")
        dataclass_response = client.get("/greetings/dataclass")
        response_response = client.get("/greetings/response")
        http_response = client.get("/greetings/http-response")
        none_response = client.get("/greetings/none")

    assert dict_response.status_code == 200
    assert dict_response.json() == {"message": "hello"}
    assert list_response.status_code == 200
    assert list_response.json() == ["hello", "world"]
    assert dataclass_response.status_code == 200
    assert dataclass_response.json() == {"status": "ok"}
    assert response_response.status_code == 202
    assert response_response.text == "plain"
    assert http_response.status_code == 203
    assert http_response.json() == {"message": "wrapped"}
    assert none_response.status_code == 204
    assert none_response.text == ""


def test_create_app_reuses_a_singleton_controller_instance_per_request() -> None:
    @Injectable
    class CounterService:
        pass

    @Controller("/controllers")
    class ControllerIdentityController:
        def __init__(self, counter_service: CounterService) -> None:
            self.counter_service = counter_service

        @Get("/identity")
        def read_identity(self) -> dict[str, int]:
            return {
                "controller_id": id(self),
                "service_id": id(self.counter_service),
            }

    @Module(
        controllers=[ControllerIdentityController],
        providers=[CounterService],
        exports=[CounterService],
    )
    class AppModule:
        pass

    with TestClient(cast(Any, create_app(AppModule))) as client:
        first_response = client.get("/controllers/identity")
        second_response = client.get("/controllers/identity")

    first_payload = first_response.json()
    second_payload = second_response.json()

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert first_payload["controller_id"] == second_payload["controller_id"]
    assert first_payload["service_id"] == second_payload["service_id"]


def test_create_app_exposes_response_token_during_controller_resolution() -> None:
    @Controller("/responses")
    class ResponseController:
        def __init__(self, response: Response) -> None:
            self._response = response

        @Get("/")
        def read_response(self) -> dict[str, str]:
            self._response.status_code = 201
            self._response.headers["x-response-token"] = "yes"
            return {"status": "ok"}

    @Module(controllers=[ResponseController])
    class AppModule:
        pass

    with TestClient(cast(Any, create_app(AppModule))) as client:
        response = client.get("/responses")

    assert response.status_code == 201
    assert response.headers["x-response-token"] == "yes"
    assert response.json() == {"status": "ok"}


def test_create_app_binds_request_path_query_and_json_body_values() -> None:
    @Injectable
    class UsersService:
        pass

    @Controller("/users")
    class UsersController:
        def __init__(self, users_service: UsersService) -> None:
            self.users_service = users_service

        @Get("/{user_id}")
        def read_user(
            self,
            request: Request,
            user_id: int,
            verbose: bool = False,
            page: int = 1,
        ) -> dict[str, object]:
            return {
                "path": request.url.path,
                "user_id": user_id,
                "verbose": verbose,
                "page": page,
            }

        @Post("/")
        def create_user(self, payload: CreateUserPayload) -> dict[str, object]:
            return {
                "name": payload.name,
                "admin": payload.admin,
            }

        @Post("/fields")
        def create_user_from_fields(self, name: str, admin: bool) -> dict[str, object]:
            return {
                "name": name,
                "admin": admin,
            }

    @Module(controllers=[UsersController], providers=[UsersService], exports=[UsersService])
    class AppModule:
        pass

    with TestClient(cast(Any, create_app(AppModule))) as client:
        read_response = client.get("/users/41?verbose=true&page=2")
        payload_response = client.post("/users", json={"name": "Ada", "admin": True})
        field_response = client.post("/users/fields", json={"name": "Moses", "admin": False})

    assert read_response.status_code == 200
    assert read_response.json() == {
        "path": "/users/41",
        "user_id": 41,
        "verbose": True,
        "page": 2,
    }
    assert payload_response.status_code == 200
    assert payload_response.json() == {"name": "Ada", "admin": True}
    assert field_response.status_code == 200
    assert field_response.json() == {"name": "Moses", "admin": False}


def test_create_app_allows_handlers_to_use_adapter_neutral_http_request_annotations() -> None:
    @Controller("/requests")
    class RequestController:
        @Get("/")
        def read_request(self, request: HttpRequest) -> dict[str, object]:
            return {
                "method": request.method,
                "path": request.path,
                "host": request.headers["host"],
            }

    @Module(controllers=[RequestController])
    class AppModule:
        pass

    with TestClient(cast(Any, create_app(AppModule))) as client:
        response = client.get("/requests")

    assert response.status_code == 200
    assert response.json() == {"method": "GET", "path": "/requests", "host": "testserver"}


def test_create_app_returns_a_400_response_for_invalid_bound_inputs() -> None:
    @Injectable
    class UsersService:
        pass

    @Controller("/users")
    class UsersController:
        def __init__(self, users_service: UsersService) -> None:
            self.users_service = users_service

        @Get("/{user_id}")
        def read_user(self, user_id: int) -> dict[str, int]:
            return {"user_id": user_id}

    @Module(controllers=[UsersController], providers=[UsersService], exports=[UsersService])
    class AppModule:
        pass

    with TestClient(cast(Any, create_app(AppModule))) as client:
        response = client.get("/users/not-a-number")

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Could not bind path parameter 'user_id' to int: invalid literal for int() with base 10: 'not-a-number'"
    )


def test_create_app_handles_stream_and_file_responses_through_the_response_handler(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "greeting.txt"
    file_path.write_text("hello file", encoding="utf-8")

    @Controller("/responses")
    class ResponseController:
        @Get("/stream")
        def read_stream(self) -> Iterator[bytes]:
            yield b"hello"
            yield b" "
            yield b"stream"

        @Get("/file")
        def read_file(self) -> Path:
            return file_path

    @Module(controllers=[ResponseController])
    class AppModule:
        pass

    with TestClient(cast(Any, create_app(AppModule))) as client:
        stream_response = client.get("/responses/stream")
        file_response = client.get("/responses/file")

    assert stream_response.status_code == 200
    assert stream_response.text == "hello stream"
    assert file_response.status_code == 200
    assert file_response.text == "hello file"


def test_create_app_resolves_request_scoped_providers_per_request() -> None:
    @Injectable(scope="request")
    class RequestState:
        def __init__(self, request: Request) -> None:
            self.request = request

    @Injectable(scope="request")
    class RequestAudit:
        def __init__(self, request_state: RequestState) -> None:
            self.request_state = request_state

    @Controller("/requests", scope=Scope.REQUEST)
    class RequestController:
        def __init__(self, request_state: RequestState, request_audit: RequestAudit) -> None:
            self.request_state = request_state
            self.request_audit = request_audit

        @Get("/state")
        def read_state(self) -> dict[str, object]:
            return {
                "request_id": self.request_state.request.headers["x-request-id"],
                "path": self.request_state.request.url.path,
                "request_state_id": id(self.request_state),
                "audit_request_state_id": id(self.request_audit.request_state),
            }

    @Module(
        controllers=[RequestController],
        providers=[RequestState, RequestAudit],
        exports=[RequestState, RequestAudit],
    )
    class AppModule:
        pass

    with TestClient(cast(Any, create_app(AppModule))) as client:
        first_response = client.get("/requests/state", headers={"x-request-id": "first"})
        second_response = client.get("/requests/state", headers={"x-request-id": "second"})

    first_payload = first_response.json()
    second_payload = second_response.json()

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert first_payload["request_id"] == "first"
    assert second_payload["request_id"] == "second"
    assert first_payload["path"] == "/requests/state"
    assert second_payload["path"] == "/requests/state"
    assert first_payload["request_state_id"] == first_payload["audit_request_state_id"]
    assert second_payload["request_state_id"] == second_payload["audit_request_state_id"]
    assert first_payload["request_state_id"] != second_payload["request_state_id"]
