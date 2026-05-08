"""Unit tests for the compiled controller testing harness."""

from __future__ import annotations

import pytest
from starlette.responses import JSONResponse

from bustan import (
    CallHandler,
    Controller,
    ExceptionFilter,
    ExecutionContext,
    Get,
    Guard,
    Injectable,
    Interceptor,
    Module,
    Pipe,
    UseFilters,
    UseGuards,
    UseInterceptors,
    UsePipes,
)
from bustan.testing import create_testing_module


@pytest.mark.anyio
async def test_compiled_testing_module_preserves_guards_pipes_and_interceptors() -> None:
    events: list[str] = []

    class AuthGuard(Guard):
        async def can_activate(self, context: ExecutionContext) -> bool:
            events.append("guard")
            return True

    class UppercasePipe(Pipe):
        async def transform(self, value: object, context: ExecutionContext) -> object:
            events.append(f"pipe:{context.name}:{value}")
            return str(value).upper()

    class EnvelopeInterceptor(Interceptor):
        async def intercept(
            self,
            context: ExecutionContext,
            next: CallHandler,
        ) -> object:
            events.append("interceptor:before")
            result = await next.handle()
            events.append("interceptor:after")
            return {"result": result}

    @Injectable
    class GreetingService:
        def greet(self, name: str) -> str:
            return f"production {name}"

    class FakeGreetingService:
        def greet(self, name: str) -> str:
            return f"test {name}"

    @UseGuards(AuthGuard())
    @Controller("/greetings")
    class GreetingController:
        def __init__(self, greeting_service: GreetingService) -> None:
            self._greeting_service = greeting_service

        @UsePipes(UppercasePipe())
        @UseInterceptors(EnvelopeInterceptor())
        @Get("/{name}")
        def read_greeting(self, name: str) -> dict[str, str]:
            events.append("handler")
            return {"message": self._greeting_service.greet(name)}

    @Module(
        controllers=[GreetingController], providers=[GreetingService], exports=[GreetingService]
    )
    class AppModule:
        pass

    compiled = await (
        create_testing_module(AppModule)
        .override_provider(GreetingService)
        .use_value(FakeGreetingService())
        .compile()
    )
    try:
        with compiled.create_client() as client:
            response = client.get("/greetings/ada")
    finally:
        await compiled.close()

    assert response.status_code == 200
    assert response.json() == {"result": {"message": "test ADA"}}
    assert events == [
        "guard",
        "pipe:name:ada",
        "interceptor:before",
        "handler",
        "interceptor:after",
    ]


@pytest.mark.anyio
async def test_compiled_testing_module_preserves_filters_for_provider_override_failures() -> None:
    events: list[str] = []

    class RuntimeErrorFilter(ExceptionFilter):
        exception_types = (ValueError,)

        async def catch(self, exc: Exception, context: ExecutionContext) -> object:
            events.append("filter")
            return JSONResponse({"detail": str(exc)}, status_code=422)

    @Injectable
    class GreetingService:
        def greet(self) -> str:
            return "production"

    class FailingGreetingService:
        def greet(self) -> str:
            raise ValueError("boom")

    @Controller("/greetings")
    class GreetingController:
        def __init__(self, greeting_service: GreetingService) -> None:
            self._greeting_service = greeting_service

        @UseFilters(RuntimeErrorFilter())
        @Get("/")
        def read_greeting(self) -> dict[str, str]:
            events.append("handler")
            return {"message": self._greeting_service.greet()}

    @Module(
        controllers=[GreetingController], providers=[GreetingService], exports=[GreetingService]
    )
    class AppModule:
        pass

    compiled = await (
        create_testing_module(AppModule)
        .override_provider(GreetingService)
        .use_value(FailingGreetingService())
        .compile()
    )
    try:
        with compiled.create_client() as client:
            response = client.get("/greetings")
    finally:
        await compiled.close()

    assert response.status_code == 422
    assert response.json() == {"detail": "boom"}
    assert events == ["handler", "filter"]


@pytest.mark.anyio
async def test_compiled_testing_module_exposes_route_snapshots() -> None:
    @Controller("/users")
    class UsersController:
        @Get("/")
        def index(self) -> dict[str, str]:
            return {"status": "ok"}

    @Module(controllers=[UsersController])
    class AppModule:
        pass

    compiled = await create_testing_module(AppModule).compile()
    try:
        snapshot = compiled.snapshot_routes()
    finally:
        await compiled.close()

    assert len(snapshot) == 1
    assert snapshot[0]["controller"] == "UsersController"
    assert snapshot[0]["path"] == "/users"
    assert snapshot[0]["method"] == "GET"