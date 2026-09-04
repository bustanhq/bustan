"""Integration tests for module and application lifecycle hooks."""

from typing import Any, cast

import pytest
from starlette.testclient import TestClient

from bustan import Injectable, Module, create_app
from bustan.errors import LifecycleError


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
