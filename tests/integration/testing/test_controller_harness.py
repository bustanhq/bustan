"""Integration tests for the controller testing harness."""

from __future__ import annotations

import pytest

from bustan import Controller, ExecutionContext, Get, Guard, Injectable, Module, UseGuards
from bustan.testing import create_testing_module


@pytest.mark.anyio
async def test_controller_harness_can_override_guards_without_bypassing_runtime() -> None:
    events: list[str] = []

    class DefaultGuard(Guard):
        async def can_activate(self, context: ExecutionContext) -> bool:
            events.append("default-guard")
            return False

    class AllowGuard(Guard):
        async def can_activate(self, context: ExecutionContext) -> bool:
            events.append("allow-guard")
            return True

    @Injectable
    class GreetingService:
        def greet(self) -> str:
            return "hello"

    default_guard = DefaultGuard()

    @UseGuards(default_guard)
    @Controller("/greetings")
    class GreetingController:
        def __init__(self, greeting_service: GreetingService) -> None:
            self._greeting_service = greeting_service

        @Get("/")
        def read_greeting(self) -> dict[str, str]:
            events.append("handler")
            return {"message": self._greeting_service.greet()}

    @Module(
        controllers=[GreetingController], providers=[GreetingService], exports=[GreetingService]
    )
    class AppModule:
        pass

    builder = create_testing_module(AppModule)
    builder.override_guard(default_guard).use_value(AllowGuard())
    compiled = await builder.compile()
    try:
        with compiled.create_client() as client:
            response = client.get("/greetings")
    finally:
        await compiled.close()

    assert response.status_code == 200
    assert response.json() == {"message": "hello"}
    assert events == ["allow-guard", "handler"]