"""Unit tests for test helpers and dynamic test-module construction."""

from __future__ import annotations

import pytest
from starlette.applications import Starlette

from bustan import Controller, Get, Guard, Injectable, Module
from bustan.core.module.metadata import ModuleMetadata, get_module_metadata
from bustan.errors import LifecycleError, ProviderResolutionError
from bustan.testing import (
    CompiledTestingModule,
    PipelineOverrideRegistry,
    TestingModuleBuilder,
    create_test_app,
    create_test_module,
    create_testing_module,
    override_provider,
)
from bustan.testing.builder import _require_lifecycle_manager


@Injectable
class AuditTrail:
    """A provider declared at module scope so a nested fake can annotate it."""


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
async def test_compiled_testing_module_close_runs_the_whole_teardown_sequence() -> None:
    # Tearing down a compiled testing module runs the same stages in the same order
    # as tearing down an application, because a test that never reaches the
    # pre-shutdown stage cannot show that production teardown drains anything.
    events: list[str] = []

    @Module()
    class AppModule:
        def before_application_shutdown(self, signal: str | None) -> None:
            events.append("before-shutdown")

        def on_application_shutdown(self, signal: str | None) -> None:
            events.append("shutdown")

        def on_module_destroy(self) -> None:
            events.append("destroy")

    compiled = await create_testing_module(AppModule).compile()
    await compiled.close()

    assert events == ["before-shutdown", "shutdown", "destroy"]


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

    with (
        pytest.raises(TypeError, match="does not expose a Bustan container"),
        override_provider(starlette, object(), object()),
    ):
        pass


def test_override_provider_rejects_invalid_starlette_container_state() -> None:
    starlette = Starlette()
    starlette.state.bustan_container = object()

    with (
        pytest.raises(TypeError, match="does not expose a Bustan container"),
        override_provider(starlette, object(), object()),
    ):
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


@pytest.mark.anyio
async def test_compile_starts_a_graph_whose_singleton_factory_is_async() -> None:
    # The testing surface runs the application's own startup, so a graph a served
    # application can warm is a graph a test can compile.
    async def build_connection() -> str:
        return "conn"

    @Module(
        providers=[{"provide": "CONN", "use_factory": build_connection}],
        exports=["CONN"],
    )
    class DbModule:
        pass

    @Module(imports=[DbModule])
    class AppModule:
        pass

    compiled = await create_testing_module(AppModule).compile()
    try:
        assert compiled.get("CONN") == "conn"
    finally:
        await compiled.close()


@pytest.mark.anyio
async def test_second_close_runs_no_teardown_hook_again() -> None:
    events: list[str] = []

    @Module()
    class AppModule:
        def on_application_shutdown(self, signal: str | None) -> None:
            events.append("shutdown")

        def on_module_destroy(self) -> None:
            events.append("destroy")

    compiled = await create_testing_module(AppModule).compile()
    await compiled.close()
    await compiled.close()

    assert events == ["shutdown", "destroy"]


@pytest.mark.anyio
async def test_close_reports_every_failing_teardown_hook_not_only_the_first() -> None:
    @Module()
    class FirstFailingModule:
        def on_application_shutdown(self, signal: str | None) -> None:
            raise RuntimeError("shutdown failed")

    @Module()
    class SecondFailingModule:
        def on_module_destroy(self) -> None:
            raise RuntimeError("destroy failed")

    @Module(imports=[FirstFailingModule, SecondFailingModule])
    class AppModule:
        pass

    compiled = await create_testing_module(AppModule).compile()

    with pytest.raises(LifecycleError) as failure:
        await compiled.close()

    assert "shutdown failed" in str(failure.value)
    assert "destroy failed" in str(failure.value)


@pytest.mark.anyio
async def test_compiled_application_shares_lifecycle_state_with_the_testing_module() -> None:
    # compile() drives the application's own manager, so the application agrees about
    # what has already run: closing it tears down once, and re-initializing it after a
    # close is refused rather than quietly running the init hooks a second time.
    events: list[str] = []

    @Module()
    class AppModule:
        def on_module_init(self) -> None:
            events.append("init")

        def on_application_shutdown(self, signal: str | None) -> None:
            events.append("shutdown")

    compiled = await create_testing_module(AppModule).compile()

    assert events == ["init"]

    await compiled.application.init()
    assert events == ["init"]

    await compiled.application.close()
    assert events == ["init", "shutdown"]

    await compiled.close()
    assert events == ["init", "shutdown"]

    with pytest.raises(LifecycleError, match="already closed"):
        await compiled.application.init()


@pytest.mark.anyio
async def test_class_replacement_sees_the_replaced_provider_module_dependencies() -> None:
    # A replacement stands in for the provider it replaces, so it is built with that
    # provider's visibility. Db is deliberately not exported.
    @Injectable
    class Db:
        pass

    @Injectable
    class UserService:
        def __init__(self, db: Db) -> None:
            self.db = db

    class FakeUserService:
        def __init__(self, db: Db) -> None:
            self.db = db

    @Module(providers=[Db, UserService], exports=[UserService])
    class UsersModule:
        pass

    @Module(imports=[UsersModule])
    class AppModule:
        pass

    compiled = await (
        create_testing_module(AppModule)
        .override_provider(UserService)
        .use_class(FakeUserService)
        .compile()
    )
    try:
        resolved = compiled.get(UserService)
        assert isinstance(resolved, FakeUserService)
        assert isinstance(resolved.db, Db)
    finally:
        await compiled.close()


@pytest.mark.anyio
async def test_factory_replacement_sees_the_replaced_provider_module_dependencies() -> None:
    @Injectable
    class Db:
        pass

    @Injectable
    class UserService:
        def __init__(self, db: Db) -> None:
            self.db = db

    class FakeUserService:
        def __init__(self, db: Db) -> None:
            self.db = db

    @Module(providers=[Db, UserService], exports=[UserService])
    class UsersModule:
        pass

    @Module(imports=[UsersModule])
    class AppModule:
        pass

    compiled = await (
        create_testing_module(AppModule)
        .override_provider(UserService)
        .use_factory(FakeUserService, inject=(Db,))
        .compile()
    )
    try:
        resolved = compiled.get(UserService)
        assert isinstance(resolved, FakeUserService)
        assert isinstance(resolved.db, Db)
    finally:
        await compiled.close()


@pytest.mark.anyio
async def test_async_factory_replacement_is_awaited() -> None:
    @Injectable
    class GreetingService:
        def greet(self) -> str:
            return "production"

    class FakeGreetingService:
        def greet(self) -> str:
            return "test"

    async def build_greeting() -> object:
        return FakeGreetingService()

    @Module(providers=[GreetingService], exports=[GreetingService])
    class AppModule:
        pass

    compiled = await (
        create_testing_module(AppModule)
        .override_provider(GreetingService)
        .use_factory(build_greeting)
        .compile()
    )
    try:
        assert compiled.get(GreetingService).greet() == "test"
    finally:
        await compiled.close()


@pytest.mark.anyio
async def test_unresolvable_replacement_names_the_module_that_actually_failed() -> None:
    # AuditTrail is bound, but by a module the declaring module of UserService cannot
    # see, so the failure must name that declaring module and not the root.
    @Injectable
    class UserService:
        pass

    class FakeUserService:
        def __init__(self, trail: AuditTrail) -> None:
            self.trail = trail

    @Module(providers=[AuditTrail])
    class InfrastructureModule:
        pass

    @Module(providers=[UserService], exports=[UserService])
    class UsersModule:
        pass

    @Module(imports=[InfrastructureModule, UsersModule])
    class AppModule:
        pass

    builder = create_testing_module(AppModule)
    builder.override_provider(UserService).use_class(FakeUserService)

    with pytest.raises(ProviderResolutionError) as failure:
        await builder.compile()

    assert "which UsersModule cannot see" in str(failure.value)
    assert "AppModule" not in str(failure.value)


@pytest.mark.anyio
async def test_value_override_is_visible_to_a_class_replacement() -> None:
    @Injectable
    class Clock:
        def now(self) -> str:
            return "production"

    @Injectable
    class ReportService:
        def __init__(self, clock: Clock) -> None:
            self.clock = clock

    class FrozenClock:
        def now(self) -> str:
            return "frozen"

    class FakeReportService:
        def __init__(self, clock: Clock) -> None:
            self.clock = clock

    @Module(providers=[Clock, ReportService], exports=[Clock, ReportService])
    class AppModule:
        pass

    compiled = await (
        create_testing_module(AppModule)
        .override_provider(ReportService)
        .use_class(FakeReportService)
        .override_provider(Clock)
        .use_value(FrozenClock())
        .compile()
    )
    try:
        assert compiled.get(ReportService).clock.now() == "frozen"
    finally:
        await compiled.close()


@pytest.mark.anyio
async def test_compiled_module_exposes_the_module_instances_startup_built() -> None:
    @Module()
    class AppModule:
        def on_module_init(self) -> None:
            pass

    compiled = await create_testing_module(AppModule).compile()
    try:
        instances = compiled.module_instances
        assert list(instances) == [AppModule]
        assert isinstance(instances[AppModule], AppModule)
    finally:
        await compiled.close()


def test_an_application_without_a_lifecycle_manager_is_refused() -> None:
    @Module()
    class AppModule:
        pass

    application = create_test_app(AppModule)
    application._lifecycle_manager = None

    with pytest.raises(LifecycleError, match="without a lifecycle manager"):
        _require_lifecycle_manager(application)


@pytest.mark.anyio
async def test_replacing_a_token_no_module_declares_is_refused_by_the_container() -> None:
    # A token no module binds has no declaring module to build the replacement from,
    # so the container's own rule about unknown overrides is what answers.
    class FakeService:
        pass

    @Module()
    class AppModule:
        pass

    builder = create_testing_module(AppModule)
    builder.override_provider("MISSING").use_class(FakeService)

    with pytest.raises(ProviderResolutionError, match="is not registered in the container"):
        await builder.compile()


@pytest.mark.anyio
async def test_a_non_class_token_finds_its_declaring_module() -> None:
    # A string token built while the test runs is a different object from the one the
    # module registered, so the declaring module has to be found by the token's
    # identity rather than by object identity. Dep is deliberately not exported.
    registered_token = "CONFIG"
    lookup_token = "".join(("CON", "FIG"))
    assert lookup_token == registered_token
    assert lookup_token is not registered_token

    @Injectable
    class Dep:
        def where(self) -> str:
            return "declaring module"

    @Injectable
    class RealConfig:
        def __init__(self, dep: Dep) -> None:
            self.dep = dep

    class FakeConfig:
        def __init__(self, dep: Dep) -> None:
            self.dep = dep

    @Module(
        providers=[Dep, {"provide": registered_token, "use_class": RealConfig}],
        exports=[registered_token],
    )
    class ConfigModule:
        pass

    @Module(imports=[ConfigModule])
    class AppModule:
        pass

    compiled = await (
        create_testing_module(AppModule)
        .override_provider(lookup_token)
        .use_class(FakeConfig)
        .compile()
    )
    try:
        resolved = compiled.get(registered_token)
        assert isinstance(resolved, FakeConfig)
        assert resolved.dep.where() == "declaring module"
    finally:
        await compiled.close()


@pytest.mark.anyio
async def test_a_value_override_reaches_a_non_class_token_built_at_runtime() -> None:
    registered_token = "GREETING"
    lookup_token = "".join(("GREET", "ING"))
    assert lookup_token is not registered_token

    @Module(
        providers=[{"provide": registered_token, "use_value": "production"}],
        exports=[registered_token],
    )
    class GreetingModule:
        pass

    @Module(imports=[GreetingModule])
    class AppModule:
        pass

    compiled = await (
        create_testing_module(AppModule).override_provider(lookup_token).use_value("test").compile()
    )
    try:
        assert compiled.get(registered_token) == "test"
    finally:
        await compiled.close()
