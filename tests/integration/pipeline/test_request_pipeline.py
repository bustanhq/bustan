"""Integration tests for guards, pipes, interceptors, and filters."""

from __future__ import annotations

from typing import Annotated, Any, cast

import pytest
from pydantic import BaseModel
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from bustan import (
    CallHandler,
    ExceptionFilter,
    Guard,
    Interceptor,
    Pipe,
    Controller,
    create_param_decorator,
    create_app,
    Get,
    Injectable,
    Module,
    Post,
    UseFilters,
    UseGuards,
    UseInterceptors,
    UsePipes,
)
from bustan.errors import ParameterBindingError
from bustan.pipeline.context import ExecutionContext


class CreateUserPayload(BaseModel):
    name: str
    admin: bool


RequestData = create_param_decorator(
    lambda data, ctx: ctx.get_route_contract().handler_name
    if data is None
    else ctx.switch_to_http().get_request().headers[data],
    name="RequestData",
)

CurrentPayload = create_param_decorator(
    lambda data, ctx: {"name": "Ada"},
    name="CurrentPayload",
)


class DecoratedPayload(BaseModel):
    name: str


def test_request_pipeline_executes_in_the_expected_order() -> None:
    events: list[str] = []

    class AuthGuard(Guard):
        async def can_activate(self, context: ExecutionContext) -> bool:
            events.append("guard")
            return True

    class RecordingPipe(Pipe):
        async def transform(self, value: object, context: ExecutionContext) -> object:
            events.append(f"pipe:{context.name}:{value}")
            if context.name == "name":
                return str(value).upper()
            return value

    class OuterInterceptor(Interceptor):
        async def intercept(
            self,
            context: ExecutionContext,
            next: CallHandler,
        ) -> object:
            events.append("interceptor:outer:before")
            result = await next.handle()
            events.append("interceptor:outer:after")
            return {"outer": result}

    class InnerInterceptor(Interceptor):
        async def intercept(
            self,
            context: ExecutionContext,
            next: CallHandler,
        ) -> object:
            events.append("interceptor:inner:before")
            result = await next.handle()
            events.append("interceptor:inner:after")
            return {"inner": result}

    @Injectable
    class GreetingService:
        pass

    @UseGuards(AuthGuard())
    @UseInterceptors(OuterInterceptor())
    @Controller("/greetings")
    class GreetingController:
        def __init__(self, greeting_service: GreetingService) -> None:
            self.greeting_service = greeting_service

        @UsePipes(RecordingPipe())
        @UseInterceptors(InnerInterceptor())
        @Get("/{name}")
        def greet(self, name: str, excited: bool = False) -> dict[str, object]:
            events.append(f"handler:{name}:{excited}")
            return {"message": name, "excited": excited}

    @Module(
        controllers=[GreetingController], providers=[GreetingService], exports=[GreetingService]
    )
    class AppModule:
        pass

    with TestClient(cast(Any, create_app(AppModule))) as client:
        response = client.get("/greetings/moses?excited=true")

    assert response.status_code == 200
    assert response.json() == {"outer": {"inner": {"message": "MOSES", "excited": True}}}
    assert events == [
        "guard",
        "pipe:name:moses",
        "pipe:excited:True",
        "interceptor:outer:before",
        "interceptor:inner:before",
        "handler:MOSES:True",
        "interceptor:inner:after",
        "interceptor:outer:after",
    ]


def test_request_pipeline_short_circuits_when_a_guard_rejects_the_request() -> None:
    events: list[str] = []

    class DenyGuard(Guard):
        async def can_activate(self, context: ExecutionContext) -> bool:
            events.append("guard")
            return False

    @Injectable
    class SecretService:
        pass

    @UseGuards(DenyGuard())
    @Controller("/secret")
    class SecretController:
        def __init__(self, secret_service: SecretService) -> None:
            self.secret_service = secret_service

        @Get("/")
        def read_secret(self) -> dict[str, str]:
            events.append("handler")
            return {"secret": "classified"}

    @Module(controllers=[SecretController], providers=[SecretService], exports=[SecretService])
    class AppModule:
        pass

    with TestClient(cast(Any, create_app(AppModule))) as client:
        response = client.get("/secret")

    assert response.status_code == 403
    assert response.json()["detail"].endswith("DenyGuard blocked the request")
    assert events == ["guard"]


def test_request_pipeline_uses_exception_filters_to_convert_handler_errors() -> None:
    class ValueErrorFilter(ExceptionFilter):
        exception_types = (ValueError,)

        async def catch(self, exc: Exception, context: ExecutionContext) -> object:
            request = context.request
            assert request is not None
            return JSONResponse(
                {"detail": str(exc), "path": request.url.path},
                status_code=418,
            )

    @Controller("/fails")
    class FailingController:
        @UseFilters(ValueErrorFilter())
        @Get("/boom")
        def explode(self) -> None:
            raise ValueError("boom")

    @Module(controllers=[FailingController])
    class AppModule:
        pass

    with TestClient(cast(Any, create_app(AppModule))) as client:
        response = client.get("/fails/boom")

    assert response.status_code == 418
    assert response.json() == {"detail": "boom", "path": "/fails/boom"}


def test_request_pipeline_uses_exception_filters_to_convert_binding_errors() -> None:
    class BindingErrorFilter(ExceptionFilter):
        exception_types = (ParameterBindingError,)

        async def catch(self, exc: Exception, context: ExecutionContext) -> object:
            request = context.request
            assert request is not None
            return JSONResponse(
                {"detail": str(exc), "kind": "binding", "path": request.url.path},
                status_code=422,
            )

    @Controller("/users")
    class UsersController:
        @UseFilters(BindingErrorFilter())
        @Get("/{user_id}")
        def read_user(self, user_id: int) -> dict[str, int]:
            return {"user_id": user_id}

    @Module(controllers=[UsersController])
    class AppModule:
        pass

    with TestClient(cast(Any, create_app(AppModule))) as client:
        response = client.get("/users/not-a-number")

    assert response.status_code == 422
    assert response.json() == {
        "detail": "Could not bind path parameter 'user_id' to int: invalid literal for int() with base 10: 'not-a-number'",
        "kind": "binding",
        "path": "/users/not-a-number",
    }


def test_request_pipeline_rejects_ambiguous_parameters_in_strict_binding_mode_at_startup() -> None:
    @Controller("/users", binding_mode="strict")
    class UsersController:
        @Get("/")
        def list_users(self, page: int) -> dict[str, int]:
            return {"page": page}

    @Module(controllers=[UsersController])
    class AppModule:
        pass

    with pytest.raises(ParameterBindingError, match="strict mode"):
        create_app(AppModule)


def test_request_pipeline_returns_structured_parameter_binding_errors_by_default() -> None:
    @Controller("/users")
    class UsersController:
        @Get("/{user_id}")
        def read_user(self, user_id: int) -> dict[str, int]:
            return {"user_id": user_id}

    @Module(controllers=[UsersController])
    class AppModule:
        pass

    with TestClient(cast(Any, create_app(AppModule))) as client:
        response = client.get("/users/not-a-number")

    assert response.status_code == 400
    assert response.json()["field"] == "user_id"
    assert response.json()["source"] == "path parameter"
    assert "not-a-number" in response.json()["detail"]


def test_request_pipeline_auto_validation_rejects_invalid_payloads_before_handler_invocation() -> None:
    handler_called = False

    @Controller("/users", validation_mode="auto")
    class UsersController:
        @Post("/")
        def create_user(self, payload: CreateUserPayload) -> dict[str, str]:
            nonlocal handler_called
            handler_called = True
            return {"name": payload.name}

    @Module(controllers=[UsersController])
    class AppModule:
        pass

    with TestClient(cast(Any, create_app(AppModule))) as client:
        response = client.post("/users", json={"name": "Ada"})

    assert response.status_code == 400
    assert handler_called is False
    assert response.json()["field"] == "payload"
    assert response.json()["source"] == "body"
    assert "admin" in response.json()["detail"]


def test_request_pipeline_supports_execution_context_backed_custom_param_decorators() -> None:
    @Controller("/context")
    class ContextController:
        @Get("/")
        def read_context(
            self,
            handler_name: Annotated[str, RequestData],
            request_id: Annotated[str, RequestData("x-request-id")],
        ) -> dict[str, str]:
            return {"handler": handler_name, "request_id": request_id}

    @Module(controllers=[ContextController])
    class AppModule:
        pass

    with TestClient(cast(Any, create_app(AppModule))) as client:
        response = client.get("/context", headers={"x-request-id": "id-123"})

    assert response.status_code == 200
    assert response.json() == {"handler": "read_context", "request_id": "id-123"}


def test_request_pipeline_validates_custom_param_decorators_only_when_opted_in() -> None:
    @Controller("/raw")
    class RawController:
        @Get("/")
        def read_raw(self, payload: Annotated[DecoratedPayload, CurrentPayload]) -> dict[str, str]:
            return {"kind": type(payload).__name__}

    @Controller("/validated", validate_custom_decorators=True)
    class ValidatedController:
        @Get("/")
        def read_validated(
            self,
            payload: Annotated[DecoratedPayload, CurrentPayload],
        ) -> dict[str, str]:
            return {"kind": type(payload).__name__}

    @Module(controllers=[RawController, ValidatedController])
    class AppModule:
        pass

    with TestClient(cast(Any, create_app(AppModule))) as client:
        raw_response = client.get("/raw")
        validated_response = client.get("/validated")

    assert raw_response.status_code == 200
    assert raw_response.json() == {"kind": "dict"}
    assert validated_response.status_code == 200
    assert validated_response.json() == {"kind": "DecoratedPayload"}
