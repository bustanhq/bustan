"""Unit tests for test helpers and dynamic test-module construction."""

from __future__ import annotations

import pytest

from bustan import Controller, Get, Guard, Injectable, Module
from bustan.core.module.metadata import ModuleMetadata, get_module_metadata
from bustan.testing import (
    CompiledTestingModule,
    PipelineOverrideRegistry,
    TestingModuleBuilder,
    create_test_module,
    create_testing_module,
)


def test_create_test_module_builds_module_metadata_from_arguments() -> None:
    @Injectable
    class UserService:
        pass

    @Controller("/users")
    class UserController:
        @Get("/")
        def list_users(self) -> list[dict[str, str]]:
            return [{"name": "Ada"}]

    TestUsersModule = create_test_module(
        name="TestUsersModule",
        controllers=[UserController],
        providers=[UserService],
        exports=[UserService],
    )

    assert TestUsersModule.__name__ == "TestUsersModule"
    assert get_module_metadata(TestUsersModule) == ModuleMetadata(
        imports=(),
        controllers=(UserController,),
        providers=(UserService,),
        exports=(UserService,),
    )


@pytest.mark.anyio
async def test_testing_module_builder_compiles_and_applies_provider_overrides() -> None:
    @Injectable
    class GreetingService:
        def greet(self) -> str:
            return "production"

    @Module(providers=[GreetingService], exports=[GreetingService])
    class AppModule:
        pass

    compiled = await (
        create_testing_module(AppModule)
        .override_provider(GreetingService)
        .use_value(type("FakeGreetingService", (), {"greet": staticmethod(lambda: "test")})())
        .compile()
    )

    assert isinstance(compiled, CompiledTestingModule)
    assert compiled.get(GreetingService).greet() == "test"

    await compiled.close()


def test_pipeline_override_registry_rewrites_metadata() -> None:
    class DefaultGuard(Guard):
        pass

    class ReplacementGuard(Guard):
        pass

    registry = PipelineOverrideRegistry()
    registry.guards[DefaultGuard] = ReplacementGuard

    from bustan.pipeline.metadata import PipelineMetadata

    overridden = registry.apply_to_metadata(PipelineMetadata(guards=(DefaultGuard,)))

    assert overridden.guards == (ReplacementGuard,)
    assert overridden.pipes == ()


def test_create_testing_module_returns_builder() -> None:
    @Module()
    class AppModule:
        pass

    builder = create_testing_module(AppModule)

    assert isinstance(builder, TestingModuleBuilder)
