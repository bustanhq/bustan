"""Integration tests for guards, pipes, interceptors, and filters."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from star import (
    ExceptionFilter,
    Guard,
    Interceptor,
    Pipe,
    Controller,
    create_app,
    Get,
    Injectable,
    Module,
    UseFilters,
    UseGuards,
    UseInterceptors,
    UsePipes,
)
from star.errors import ParameterBindingError
from star.pipeline.context import HandlerContext, ParameterContext, RequestContext


def test_request_pipeline_executes_in_the_expected_order() -> None:
    events: list[str] = []

    class AuthGuard(Guard):
        async def can_activate(self, context: RequestContext) -> bool:
            events.append("guard")
            return True

    class RecordingPipe(Pipe):
        async def transform(self, value: object, context: ParameterContext) -> object:
            events.append(f"pipe:{context.name}:{value}")
            if context.name == "name":
                return str(value).upper()
            return value

    class OuterInterceptor(Interceptor):
        async def intercept(
            self,
            context: HandlerContext,
            call_next: Callable[[], Awaitable[object]],
        ) -> object:
            events.append("interceptor:outer:before")
            result = await call_next()
            events.append("interceptor:outer:after")
            return {"outer": result}

    class InnerInterceptor(Interceptor):
        async def intercept(
            self,
            context: HandlerContext,
            call_next: Callable[[], Awaitable[object]],
        ) -> object:
            events.append("interceptor:inner:before")
            result = await call_next()
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

    @Module(controllers=[GreetingController], providers=[GreetingService], exports=[GreetingService])
    class AppModule:
        pass

    with TestClient(create_app(AppModule)) as client:
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
        async def can_activate(self, context: RequestContext) -> bool:
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

    with TestClient(create_app(AppModule)) as client:
        response = client.get("/secret")

    assert response.status_code == 403
    assert response.json()["detail"].endswith("DenyGuard blocked the request")
    assert events == ["guard"]


def test_request_pipeline_uses_exception_filters_to_convert_handler_errors() -> None:
    class ValueErrorFilter(ExceptionFilter):
        exception_types = (ValueError,)

        async def catch(self, exc: Exception, context: RequestContext) -> object:
            return JSONResponse(
                {"detail": str(exc), "path": context.request.url.path},
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

    with TestClient(create_app(AppModule)) as client:
        response = client.get("/fails/boom")

    assert response.status_code == 418
    assert response.json() == {"detail": "boom", "path": "/fails/boom"}


def test_request_pipeline_uses_exception_filters_to_convert_binding_errors() -> None:
    class BindingErrorFilter(ExceptionFilter):
        exception_types = (ParameterBindingError,)

        async def catch(self, exc: Exception, context: RequestContext) -> object:
            return JSONResponse(
                {"detail": str(exc), "kind": "binding", "path": context.request.url.path},
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

    with TestClient(create_app(AppModule)) as client:
        response = client.get("/users/not-a-number")

    assert response.status_code == 422
    assert response.json() == {
        "detail": "Could not bind path parameter 'user_id' to int: invalid literal for int() with base 10: 'not-a-number'",
        "kind": "binding",
        "path": "/users/not-a-number",
    }