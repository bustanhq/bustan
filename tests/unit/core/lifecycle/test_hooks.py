"""Unit tests for lifecycle protocols and runners."""

from __future__ import annotations

import pytest

from bustan import Injectable, Module
from bustan.core.ioc.container import build_container
from bustan.core.lifecycle.hooks import (
    BeforeApplicationShutdown,
    OnApplicationBootstrap,
    OnApplicationShutdown,
    OnModuleDestroy,
    OnModuleInit,
)
from bustan.core.lifecycle.runner import (
    run_before_shutdown_hooks,
    run_bootstrap_hooks,
    run_destroy_hooks,
    run_init_hooks,
    run_shutdown_hooks,
)
from bustan.core.module.graph import build_module_graph


def test_lifecycle_protocols_are_runtime_checkable() -> None:
    class Hooked:
        def on_module_init(self) -> None:
            pass

        def on_application_bootstrap(self) -> None:
            pass

        def before_application_shutdown(self, signal: str | None) -> None:
            pass

        def on_application_shutdown(self, signal: str | None) -> None:
            pass

        def on_module_destroy(self) -> None:
            pass

    hooked = Hooked()
    assert isinstance(hooked, OnModuleInit)
    assert isinstance(hooked, OnApplicationBootstrap)
    assert isinstance(hooked, BeforeApplicationShutdown)
    assert isinstance(hooked, OnApplicationShutdown)
    assert isinstance(hooked, OnModuleDestroy)


@pytest.mark.anyio
async def test_lifecycle_runners_call_module_and_provider_hooks_in_order() -> None:
    events: list[str] = []

    @Injectable
    class HookedService:
        def on_module_init(self) -> None:
            events.append("service:init")

        def on_application_bootstrap(self) -> None:
            events.append("service:startup")

        def before_application_shutdown(self, signal: str | None) -> None:
            events.append(f"service:before_shutdown:{signal}")

        def on_application_shutdown(self, signal: str | None) -> None:
            events.append("service:shutdown")

        def on_module_destroy(self) -> None:
            events.append("service:destroy")

    @Module(providers=[HookedService])
    class ChildModule:
        def on_module_init(self) -> None:
            events.append("child:init")

        def on_application_bootstrap(self) -> None:
            events.append("child:startup")

        def before_application_shutdown(self, signal: str | None) -> None:
            events.append(f"child:before_shutdown:{signal}")

        def on_application_shutdown(self, signal: str | None) -> None:
            events.append("child:shutdown")

        def on_module_destroy(self) -> None:
            events.append("child:destroy")

    @Module(imports=[ChildModule])
    class AppModule:
        def on_module_init(self) -> None:
            events.append("app:init")

        def on_application_bootstrap(self) -> None:
            events.append("app:startup")

        def before_application_shutdown(self, signal: str | None) -> None:
            events.append(f"app:before_shutdown:{signal}")

        def on_application_shutdown(self, signal: str | None) -> None:
            events.append("app:shutdown")

        def on_module_destroy(self) -> None:
            events.append("app:destroy")

    graph = build_module_graph(AppModule)
    container = build_container(graph)

    module_instances = await run_init_hooks(graph, container)
    await run_bootstrap_hooks(graph, container, module_instances)
    await run_before_shutdown_hooks(graph, container, module_instances)
    await run_shutdown_hooks(graph, container, module_instances)
    await run_destroy_hooks(graph, container, module_instances)

    assert events[:3] == ["app:init", "child:init", "service:init"]
    assert "service:startup" in events
    assert "service:before_shutdown:None" in events
    assert events[-3:] == ["child:destroy", "app:destroy", "service:destroy"]
