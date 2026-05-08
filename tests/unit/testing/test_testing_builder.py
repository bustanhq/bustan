"""Unit tests for test helpers and dynamic test-module construction."""

from __future__ import annotations

import pytest
from starlette.applications import Starlette

from bustan import Controller, Get, Guard, Injectable, Module
from bustan.core.module.metadata import ModuleMetadata, get_module_metadata
from bustan.testing import (
    CompiledTestingModule,
    PipelineOverrideRegistry,
    TestingModuleBuilder,
    create_test_app,
    create_test_module,
    create_testing_module,
    override_provider,
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


@pytest.mark.anyio
async def test_compiled_testing_module_close_runs_shutdown_and_destroy_hooks() -> None:
    events: list[str] = []

    @Module()
    class AppModule:
        def on_application_shutdown(self, signal: str | None) -> None:
            events.append("shutdown")

        def on_module_destroy(self) -> None:
            events.append("destroy")

    compiled = await create_testing_module(AppModule).compile()
    await compiled.close()

    assert events == ["shutdown", "destroy"]


@pytest.mark.anyio
async def test_compile_runs_init_and_bootstrap_hooks_once() -> None:
    events: list[str] = []

    @Module()
    class AppModule:
        def on_module_init(self) -> None:
            events.append("init")

        def on_application_bootstrap(self) -> None:
            events.append("startup")

        def on_application_shutdown(self, signal: str | None) -> None:
            events.append("shutdown")

        def on_module_destroy(self) -> None:
            events.append("destroy")

    compiled = await create_testing_module(AppModule).compile()
    await compiled.close()

    assert events == ["init", "startup", "shutdown", "destroy"]


@pytest.mark.anyio
async def test_testing_module_builder_supports_class_and_factory_provider_overrides() -> None:
    @Injectable
    class GreetingService:
        def greet(self) -> str:
            return "production"

    class GreetingReplacement:
        def greet(self) -> str:
            return "class"

    @Injectable
    class CounterService:
        def count(self) -> int:
            return 1

    def build_counter() -> object:
        return type("CounterReplacement", (), {"count": staticmethod(lambda: 2)})()

    @Module(providers=[GreetingService, CounterService], exports=[GreetingService, CounterService])
    class AppModule:
        pass

    compiled = await (
        create_testing_module(AppModule)
        .override_provider(GreetingService)
        .use_class(GreetingReplacement)
        .override_provider(CounterService)
        .use_factory(build_counter)
        .compile()
    )
    try:
        assert compiled.resolve(GreetingService).greet() == "class"
        assert compiled.get(CounterService).count() == 2
    finally:
        await compiled.close()


def test_override_provider_restores_previous_override_and_supports_application_targets() -> None:
    @Injectable
    class GreetingService:
        def greet(self) -> str:
            return "production"

    @Module(providers=[GreetingService], exports=[GreetingService])
    class AppModule:
        pass

    application = create_test_app(AppModule)
    original = object()
    replacement = object()
    application.container.override(GreetingService, original)

    with override_provider(application.container, GreetingService, replacement):
        assert application.container.get_override(GreetingService) is replacement

    assert application.container.get_override(GreetingService) is original

    with override_provider(application, GreetingService, replacement):
        assert application.container.get_override(GreetingService) is replacement

    assert application.container.get_override(GreetingService) is original

    server = application.get_http_server()
    with override_provider(server, GreetingService, replacement):
        assert application.container.get_override(GreetingService) is replacement

    assert application.container.get_override(GreetingService) is original

    starlette = Starlette()
    starlette.state.bustan_container = application.container
    with override_provider(starlette, GreetingService, replacement):
        assert application.container.get_override(GreetingService) is replacement

    assert application.container.get_override(GreetingService) is original


def test_override_provider_rejects_starlette_targets_without_a_bustan_container() -> None:
    starlette = Starlette()

    with pytest.raises(TypeError, match="does not expose a Bustan container"):
        with override_provider(starlette, object(), object()):
            pass


def test_override_provider_rejects_invalid_starlette_container_state() -> None:
    starlette = Starlette()
    starlette.state.bustan_container = object()

    with pytest.raises(TypeError, match="does not expose a Bustan container"):
        with override_provider(starlette, object(), object()):
            pass


@pytest.mark.anyio
async def test_testing_module_builder_exposes_client_and_pipeline_override_builders() -> None:
    class DefaultGuard(Guard):
        pass

    class DefaultPipe:
        pass

    class DefaultInterceptor:
        pass

    class DefaultFilter:
        pass

    @Controller("/users")
    class UsersController:
        @Get("/")
        def read_users(self) -> dict[str, str]:
            return {"status": "ok"}

    @Module(controllers=[UsersController])
    class AppModule:
        pass

    builder = create_testing_module(AppModule)
    builder.override_guard(DefaultGuard).use_value(object())
    builder.override_pipe(DefaultPipe).use_class(object())
    builder.override_interceptor(DefaultInterceptor).use_value(object())
    builder.override_filter(DefaultFilter).use_class(object())

    compiled = await builder.compile()
    try:
        snapshot = compiled.snapshot_routes()
        with compiled.create_client() as client:
            response = client.get("/users")

        assert response.status_code == 200
        assert compiled.diff_routes(snapshot) == ()
        assert builder._pipeline_overrides.guards[DefaultGuard] is not None
        assert builder._pipeline_overrides.pipes[DefaultPipe] is not None
        assert builder._pipeline_overrides.interceptors[DefaultInterceptor] is not None
        assert builder._pipeline_overrides.filters[DefaultFilter] is not None
    finally:
        await compiled.close()
