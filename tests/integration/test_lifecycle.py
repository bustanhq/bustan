"""Integration tests for module and application lifecycle hooks."""

import pytest
from starlette.testclient import TestClient

from typing import Any, cast
from bustan import create_app, Module
from bustan.errors import LifecycleError


def test_create_app_runs_lifecycle_hooks_in_startup_and_shutdown_order() -> None:
    events: list[str] = []

    @Module()
    class FeatureModule:
        def on_module_init(self) -> None:
            events.append("feature:module_init")

        async def on_app_startup(self) -> None:
            events.append("feature:app_startup")

        async def on_app_shutdown(self) -> None:
            events.append("feature:app_shutdown")

        def on_module_destroy(self) -> None:
            events.append("feature:module_destroy")

    @Module(imports=[FeatureModule])
    class AppModule:
        def on_module_init(self) -> None:
            events.append("app:module_init")

        def on_app_startup(self) -> None:
            events.append("app:app_startup")

        def on_app_shutdown(self) -> None:
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

    with pytest.raises(LifecycleError, match="BrokenModule.on_module_init failed: boom"):
        with TestClient(cast(Any, create_app(BrokenModule))):
            pass
