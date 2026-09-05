"""Integration tests for module and application lifecycle hooks."""

from typing import Any, cast

import pytest
from starlette.testclient import TestClient

from bustan import Injectable, InjectionToken, Module, create_app, create_app_context
from bustan.errors import LifecycleError, ProviderResolutionError


def test_create_app_runs_lifecycle_hooks_in_startup_and_shutdown_order() -> None:
    events: list[str] = []

    @Module()
    class FeatureModule:
        def on_module_init(self) -> None:
            events.append("feature:module_init")

        async def on_application_bootstrap(self) -> None:
            events.append("feature:app_startup")

        async def on_application_shutdown(self, signal: str | None) -> None:
            events.append("feature:app_shutdown")

        def on_module_destroy(self) -> None:
            events.append("feature:module_destroy")

    @Module(imports=[FeatureModule])
    class AppModule:
        def on_module_init(self) -> None:
            events.append("app:module_init")

        def on_application_bootstrap(self) -> None:
            events.append("app:app_startup")

        def on_application_shutdown(self, signal: str | None) -> None:
            events.append("app:app_shutdown")

        async def on_module_destroy(self) -> None:
            events.append("app:module_destroy")

    with TestClient(cast(Any, create_app(AppModule))):
        assert events == [
            "app:module_init",
            "feature:module_init",
            "app:app_startup",
            "feature:app_startup",
        ]

    assert events == [
        "app:module_init",
        "feature:module_init",
        "app:app_startup",
        "feature:app_startup",
        "feature:app_shutdown",
        "app:app_shutdown",
        "feature:module_destroy",
        "app:module_destroy",
    ]


def test_create_app_surfaces_lifecycle_hook_failures() -> None:
    @Module()
    class BrokenModule:
        def on_module_init(self) -> None:
            raise RuntimeError("boom")

    with (
        pytest.raises(LifecycleError, match="BrokenModule.on_module_init failed: boom"),
        TestClient(cast(Any, create_app(BrokenModule))),
    ):
        pass


def test_provider_shutdown_hooks_run_in_reverse_creation_order() -> None:
    events: list[str] = []

    @Injectable
    class Db:
        def on_application_shutdown(self, signal: str | None) -> None:
            events.append("db:shutdown")

    @Injectable
    class UsesDb:
        def __init__(self, db: Db) -> None:
            self.db = db

        def on_application_shutdown(self, signal: str | None) -> None:
            events.append("uses_db:shutdown")

    @Module(providers=[Db, UsesDb], exports=[UsesDb])
    class AppModule:
        pass

    with TestClient(cast(Any, create_app(AppModule))):
        pass

    assert events == ["uses_db:shutdown", "db:shutdown"]


def test_one_failing_shutdown_hook_does_not_abort_remaining_teardown() -> None:
    events: list[str] = []

    @Module()
    class BrokenModule:
        def on_application_shutdown(self, signal: str | None) -> None:
            raise RuntimeError("shutdown boom")

    @Module()
    class HealthyModule:
        def on_application_shutdown(self, signal: str | None) -> None:
            events.append("healthy:shutdown")

        def on_module_destroy(self) -> None:
            events.append("healthy:destroy")

    @Module(imports=[BrokenModule, HealthyModule])
    class AppModule:
        pass

    with (
        pytest.raises(LifecycleError, match="shutdown boom"),
        TestClient(cast(Any, create_app(AppModule))),
    ):
        pass

    assert events == ["healthy:shutdown", "healthy:destroy"]


def test_a_failed_startup_tears_down_what_it_had_already_built() -> None:
    events: list[str] = []

    @Injectable
    class Pool:
        def on_module_init(self) -> None:
            events.append("pool:open")

        def on_module_destroy(self) -> None:
            events.append("pool:close")

    @Module(providers=[Pool], exports=[Pool])
    class PoolModule:
        pass

    @Module(imports=[PoolModule])
    class AppModule:
        def on_application_bootstrap(self) -> None:
            raise RuntimeError("boom")

    with (
        pytest.raises(LifecycleError, match="AppModule.on_application_bootstrap failed: boom"),
        TestClient(cast(Any, create_app(AppModule))),
    ):
        pass

    assert events == ["pool:open", "pool:close"]


def test_a_second_client_block_starts_the_application_again() -> None:
    events: list[str] = []

    @Injectable
    class Pool:
        def on_application_bootstrap(self) -> None:
            events.append("open")

        def on_module_destroy(self) -> None:
            events.append("close")

    @Module(providers=[Pool], exports=[Pool])
    class AppModule:
        pass

    app = create_app(AppModule)

    with TestClient(cast(Any, app)):
        pass
    with TestClient(cast(Any, app)):
        pass

    assert events == ["open", "close", "open", "close"]


def test_a_value_provider_takes_no_part_in_the_lifecycle() -> None:
    class UnboundHooks:
        def on_module_init(self) -> None:
            raise AssertionError("a hook was called on a class handed over as a value")

        def on_module_destroy(self) -> None:
            raise AssertionError("a hook was called on a class handed over as a value")

    token = InjectionToken("UNBOUND")

    @Module(providers=[{"provide": token, "use_value": UnboundHooks}])
    class AppModule:
        pass

    with TestClient(cast(Any, create_app(AppModule))) as client:
        assert client is not None


@pytest.mark.anyio
async def test_a_closed_context_refuses_to_resolve_until_it_is_started_again() -> None:
    @Injectable
    class Pool:
        def __init__(self) -> None:
            self.opened = False

        async def on_module_init(self) -> None:
            self.opened = True

        async def on_module_destroy(self) -> None:
            self.opened = False

    @Module(providers=[Pool], exports=[Pool])
    class AppModule:
        pass

    context = create_app_context(AppModule)
    await context.init()
    first = context.get(Pool)
    assert first.opened is True

    await context.close()
    assert first.opened is False

    with pytest.raises(ProviderResolutionError) as raised:
        context.get(Pool)
    assert "Pool" in str(raised.value)
    assert "Start the application again" in str(raised.value)

    await context.init()
    second = context.get(Pool)

    assert second is not first
    assert second.opened is True

    await context.close()


def test_an_http_application_refuses_to_resolve_between_two_client_blocks() -> None:
    @Injectable
    class Pool:
        def __init__(self) -> None:
            self.opened = False

        def on_application_bootstrap(self) -> None:
            self.opened = True

        def on_module_destroy(self) -> None:
            self.opened = False

    @Module(providers=[Pool], exports=[Pool])
    class AppModule:
        pass

    app = create_app(AppModule)

    with TestClient(cast(Any, app)):
        first = app.get(Pool)
        assert first.opened is True

    with pytest.raises(ProviderResolutionError, match="has been shut down"):
        app.get(Pool)

    with TestClient(cast(Any, app)):
        second = app.get(Pool)
        assert second is not first
        assert second.opened is True
