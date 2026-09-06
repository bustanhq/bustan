"""Unit tests for which instances a lifecycle stage is dispatched to."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast
from unittest.mock import MagicMock

import pytest
from starlette.requests import Request

from bustan import Injectable, InjectionToken, Module, Scope
from bustan.kernel.errors import InvalidModuleError, LifecycleError
from bustan.kernel.ioc.container import build_container
from bustan.kernel.lifecycle.manager import LifecycleManager
from bustan.kernel.lifecycle.runner import (
    build_module_instance,
    constructed_instances,
    run_destroy_hooks,
    run_init_hooks,
)
from bustan.kernel.module.graph import build_module_graph

if TYPE_CHECKING:
    from tests.conftest import HttpRequestFactory


class HookRecorder:
    """A provider that records every lifecycle hook it is handed."""

    def __init__(self, name: str, events: list[str]) -> None:
        self.name = name
        self.events = events

    def on_module_init(self) -> None:
        self.events.append(f"{self.name}:init")

    def on_application_bootstrap(self) -> None:
        self.events.append(f"{self.name}:bootstrap")

    def before_application_shutdown(self, signal: str | None) -> None:
        self.events.append(f"{self.name}:before_shutdown:{signal}")

    def on_application_shutdown(self, signal: str | None) -> None:
        self.events.append(f"{self.name}:shutdown")

    def on_module_destroy(self) -> None:
        self.events.append(f"{self.name}:destroy")


class UnboundHooks:
    """A class whose hooks need an instance, so calling one on the class fails."""

    def on_module_init(self) -> None:
        raise AssertionError("the framework called a hook on a class handed to it as a value")

    def on_module_destroy(self) -> None:
        raise AssertionError("the framework called a hook on a class handed to it as a value")


@pytest.mark.anyio
async def test_a_class_handed_over_as_a_value_receives_no_lifecycle_hook() -> None:
    token = InjectionToken("UNBOUND")

    @Module(providers=[{"provide": token, "use_value": UnboundHooks}])
    class AppModule:
        pass

    manager = _manager_for(AppModule)

    await manager.startup()
    await manager.shutdown()


@pytest.mark.anyio
async def test_a_mock_handed_over_as_a_value_receives_no_lifecycle_hook() -> None:
    client = MagicMock()
    token = InjectionToken("CLIENT")

    @Module(providers=[{"provide": token, "use_value": client}])
    class AppModule:
        pass

    manager = _manager_for(AppModule)

    await manager.startup()
    await manager.shutdown()

    assert client.method_calls == []


@pytest.mark.anyio
async def test_one_object_bound_under_two_tokens_receives_each_hook_once() -> None:
    events: list[str] = []
    shared = HookRecorder("shared", events)
    first = InjectionToken("FIRST")
    second = InjectionToken("SECOND")

    @Module(
        providers=[
            {"provide": first, "use_factory": lambda: shared},
            {"provide": second, "use_factory": lambda: shared},
        ]
    )
    class AppModule:
        pass

    manager = _manager_for(AppModule)

    await manager.startup()
    await manager.shutdown()

    assert events == [
        "shared:init",
        "shared:bootstrap",
        "shared:before_shutdown:None",
        "shared:shutdown",
        "shared:destroy",
    ]


@pytest.mark.anyio
async def test_an_alias_does_not_make_its_target_a_second_participant() -> None:
    events: list[str] = []

    @Injectable
    class Service(HookRecorder):
        def __init__(self) -> None:
            super().__init__("service", events)

    alias = InjectionToken("ALIAS")

    @Module(providers=[Service, {"provide": alias, "use_existing": Service}])
    class AppModule:
        pass

    manager = _manager_for(AppModule)

    await manager.startup()

    assert events == ["service:init", "service:bootstrap"]


@pytest.mark.anyio
async def test_constructed_instances_are_listed_in_construction_order() -> None:
    @Injectable
    class Dependency:
        pass

    @Injectable
    class Dependent:
        def __init__(self, dependency: Dependency) -> None:
            self.dependency = dependency

    value_token = InjectionToken("VALUE")

    @Module(
        providers=[Dependent, Dependency, {"provide": value_token, "use_value": object()}],
        exports=[Dependent],
    )
    class AppModule:
        pass

    graph = build_module_graph(AppModule)
    container = build_container(graph)
    await run_init_hooks(graph, container)

    tokens = [participant.token for participant in constructed_instances(container)]
    assert tokens == [Dependency, Dependent]


@pytest.mark.anyio
async def test_a_durable_provider_with_an_application_partition_is_warmed_and_torn_down() -> None:
    events: list[str] = []

    @Injectable(scope=Scope.DURABLE)
    class TenantPool(HookRecorder):
        def __init__(self) -> None:
            super().__init__("pool", events)

        @classmethod
        def get_durable_context_key(cls, request: Request | None) -> str:
            return "application" if request is None else request.headers["x-tenant-id"]

    @Module(providers=[TenantPool], exports=[TenantPool])
    class AppModule:
        pass

    manager = _manager_for(AppModule)

    await manager.startup()
    assert events == ["pool:init", "pool:bootstrap"]

    await manager.shutdown()
    assert events[-3:] == ["pool:before_shutdown:None", "pool:shutdown", "pool:destroy"]


@pytest.mark.anyio
async def test_a_durable_partition_created_while_serving_takes_part_in_teardown(
    build_http_request: HttpRequestFactory,
) -> None:
    events: list[str] = []

    @Injectable(scope=Scope.DURABLE)
    class TenantPool(HookRecorder):
        def __init__(self) -> None:
            super().__init__("pool", events)

        @classmethod
        def get_durable_context_key(cls, request: Request | None) -> str:
            assert request is not None
            return request.headers["x-tenant-id"]

    @Module(providers=[TenantPool], exports=[TenantPool])
    class AppModule:
        pass

    graph = build_module_graph(AppModule)
    container = build_container(graph)
    manager = LifecycleManager(graph, container)

    await manager.startup()
    # A key this provider can only derive from a request means it has no partition
    # belonging to the application, so warm-up built nothing.
    assert events == []

    request = build_http_request(path="/items", headers=[(b"x-tenant-id", b"tenant-a")])
    container.resolve(TenantPool, module=AppModule, request=request)
    await manager.shutdown()

    assert events == ["pool:before_shutdown:None", "pool:shutdown", "pool:destroy"]


@pytest.mark.anyio
async def test_an_asynchronous_provider_hook_is_awaited() -> None:
    events: list[str] = []

    @Injectable
    class Pool:
        async def on_application_bootstrap(self) -> None:
            events.append("open")

        async def on_module_destroy(self) -> None:
            events.append("close")

    @Module(providers=[Pool], exports=[Pool])
    class AppModule:
        pass

    manager = _manager_for(AppModule)

    await manager.startup()
    await manager.shutdown()

    assert events == ["open", "close"]


@pytest.mark.anyio
async def test_a_failing_provider_hook_names_the_token_it_was_dispatched_to() -> None:
    token = InjectionToken("BROKEN")

    class Broken:
        def on_module_init(self) -> None:
            raise RuntimeError("boom")

    @Module(providers=[{"provide": token, "use_factory": Broken}])
    class AppModule:
        pass

    manager = _manager_for(AppModule)

    with pytest.raises(LifecycleError, match=r"InjectionToken\('BROKEN'\).on_module_init failed"):
        await manager.startup()


@pytest.mark.anyio
async def test_a_teardown_hook_that_fails_does_not_stop_the_remaining_providers() -> None:
    events: list[str] = []

    @Injectable
    class Healthy(HookRecorder):
        def __init__(self) -> None:
            super().__init__("healthy", events)

    @Injectable
    class Broken:
        def __init__(self, healthy: Healthy) -> None:
            self.healthy = healthy

        def on_module_destroy(self) -> None:
            raise RuntimeError("destroy boom")

    @Module(providers=[Healthy, Broken], exports=[Broken])
    class AppModule:
        pass

    graph = build_module_graph(AppModule)
    container = build_container(graph)
    await run_init_hooks(graph, container)

    errors = await run_destroy_hooks(graph, container, {})

    assert [str(error) for error in errors] == [
        "Provider lifecycle hook Broken.on_module_destroy failed: destroy boom"
    ]
    assert isinstance(errors[0].__cause__, RuntimeError)
    assert events[-1] == "healthy:destroy"


def test_a_module_the_framework_cannot_build_is_refused_by_name() -> None:
    class NeedsArguments:
        def __init__(self, dsn: str) -> None:
            self.dsn = dsn

    with pytest.raises(InvalidModuleError, match="Could not build module NeedsArguments"):
        build_module_instance(NeedsArguments, NeedsArguments)


def _manager_for(root_module: type[object]) -> LifecycleManager:
    """Build the container and lifecycle manager for one root module."""

    graph = build_module_graph(cast(Any, root_module))
    return LifecycleManager(graph, build_container(graph))
