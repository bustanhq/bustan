"""Unit tests for the lifecycle manager's startup, teardown and restart contract."""

from __future__ import annotations

from typing import Any, cast

import pytest

from bustan import Injectable, Module
from bustan.core.errors import LifecycleError, ProviderResolutionError
from bustan.core.ioc.container import Container, build_container
from bustan.core.lifecycle.manager import LifecycleErrorGroup, LifecycleManager
from bustan.core.module.graph import build_module_graph


@pytest.mark.anyio
async def test_a_startup_failure_tears_down_what_it_had_already_built() -> None:
    events: list[str] = []

    @Injectable
    class Pool:
        def on_module_init(self) -> None:
            events.append("pool:open")

        def on_module_destroy(self) -> None:
            events.append("pool:close")

    @Injectable
    class Consumer:
        def __init__(self, pool: Pool) -> None:
            self.pool = pool

        def on_module_init(self) -> None:
            events.append("consumer:open")

        def on_application_bootstrap(self) -> None:
            raise RuntimeError("boom")

        def on_module_destroy(self) -> None:
            events.append("consumer:close")

    @Module(providers=[Pool, Consumer], exports=[Consumer])
    class AppModule:
        pass

    manager, _container = _manager_for(AppModule)

    with pytest.raises(LifecycleError, match="Consumer.on_application_bootstrap failed: boom"):
        await manager.startup()

    assert events == ["pool:open", "consumer:open", "consumer:close", "pool:close"]


@pytest.mark.anyio
async def test_a_startup_failure_propagates_and_records_a_teardown_that_also_failed() -> None:
    @Injectable
    class Broken:
        def on_application_bootstrap(self) -> None:
            raise RuntimeError("startup boom")

        def on_module_destroy(self) -> None:
            raise RuntimeError("teardown boom")

    @Module(providers=[Broken], exports=[Broken])
    class AppModule:
        pass

    manager, _container = _manager_for(AppModule)

    with pytest.raises(LifecycleError) as raised:
        await manager.startup()

    assert "startup boom" in str(raised.value)
    assert raised.value.__notes__ == [
        "while undoing the failed startup: Provider lifecycle hook Broken.on_module_destroy "
        "failed: teardown boom"
    ]


@pytest.mark.anyio
async def test_a_failed_startup_is_not_torn_down_a_second_time() -> None:
    events: list[str] = []

    @Injectable
    class Pool:
        def on_application_bootstrap(self) -> None:
            raise RuntimeError("boom")

        def on_module_destroy(self) -> None:
            events.append("pool:close")

    @Module(providers=[Pool], exports=[Pool])
    class AppModule:
        pass

    manager, _container = _manager_for(AppModule)

    with pytest.raises(LifecycleError):
        await manager.startup()
    await manager.shutdown()

    assert events == ["pool:close"]
    assert manager.state.initialized is False
    assert manager.state.closed is True


@pytest.mark.anyio
async def test_hooks_failing_in_two_teardown_stages_are_raised_as_a_group() -> None:
    @Injectable
    class Broken:
        def on_application_shutdown(self, signal: str | None) -> None:
            raise RuntimeError("shutdown boom")

        def on_module_destroy(self) -> None:
            raise RuntimeError("destroy boom")

    @Module(providers=[Broken], exports=[Broken])
    class AppModule:
        pass

    manager, _container = _manager_for(AppModule)
    await manager.startup()

    with pytest.raises(LifecycleErrorGroup) as raised:
        await manager.shutdown()

    group = raised.value
    assert isinstance(group, LifecycleError)
    assert isinstance(group, ExceptionGroup)
    assert [str(member) for member in group.exceptions] == [
        "Provider lifecycle hook Broken.on_application_shutdown failed: shutdown boom",
        "Provider lifecycle hook Broken.on_module_destroy failed: destroy boom",
    ]
    assert [str(cast(BaseException, member.__cause__)) for member in group.exceptions] == [
        "shutdown boom",
        "destroy boom",
    ]


@pytest.mark.anyio
async def test_one_failing_teardown_hook_is_raised_on_its_own() -> None:
    @Injectable
    class Broken:
        def on_module_destroy(self) -> None:
            raise RuntimeError("destroy boom")

    @Module(providers=[Broken], exports=[Broken])
    class AppModule:
        pass

    manager, _container = _manager_for(AppModule)
    await manager.startup()

    with pytest.raises(LifecycleError, match="destroy boom") as raised:
        await manager.shutdown()

    assert not isinstance(raised.value, ExceptionGroup)


@pytest.mark.anyio
async def test_shutdown_drops_the_instances_it_destroyed() -> None:
    @Injectable
    class Pool:
        pass

    @Module(providers=[Pool], exports=[Pool])
    class AppModule:
        pass

    manager, container = _manager_for(AppModule)
    await manager.startup()
    before = container.resolve(Pool, module=AppModule)
    await manager.shutdown()

    assert container.resolve(Pool, module=AppModule) is not before


@pytest.mark.anyio
async def test_startup_runs_again_after_shutdown() -> None:
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

    manager, _container = _manager_for(AppModule)

    await manager.startup()
    await manager.shutdown()
    await manager.startup()

    assert events == ["open", "close", "open"]
    assert manager.state.initialized is True
    assert manager.state.closed is False


@pytest.mark.anyio
async def test_a_second_startup_within_one_cycle_runs_no_hook_twice() -> None:
    events: list[str] = []

    @Injectable
    class Pool:
        def on_application_bootstrap(self) -> None:
            events.append("open")

    @Module(providers=[Pool], exports=[Pool])
    class AppModule:
        pass

    manager, _container = _manager_for(AppModule)

    first = await manager.startup()
    second = await manager.startup()

    assert events == ["open"]
    assert first is second


@pytest.mark.anyio
async def test_a_second_shutdown_runs_no_hook_twice() -> None:
    events: list[str] = []

    @Injectable
    class Pool:
        def on_module_destroy(self) -> None:
            events.append("close")

    @Module(providers=[Pool], exports=[Pool])
    class AppModule:
        pass

    manager, _container = _manager_for(AppModule)

    await manager.startup()
    await manager.shutdown()
    await manager.shutdown()

    assert events == ["close"]


@pytest.mark.anyio
async def test_shutdown_hands_every_hook_the_signal_it_was_given() -> None:
    received: list[str | None] = []

    @Injectable
    class Pool:
        def before_application_shutdown(self, signal: str | None) -> None:
            received.append(signal)

        def on_application_shutdown(self, signal: str | None) -> None:
            received.append(signal)

    @Module(providers=[Pool], exports=[Pool])
    class AppModule:
        pass

    manager, _container = _manager_for(AppModule)

    await manager.startup()
    await manager.shutdown(signal="SIGTERM")

    assert received == ["SIGTERM", "SIGTERM"]


def _manager_for(root_module: type[object]) -> tuple[LifecycleManager, Container]:
    """Build the container and lifecycle manager for one root module."""

    graph = build_module_graph(cast(Any, root_module))
    container = build_container(graph)
    return LifecycleManager(graph, container), container


@pytest.mark.anyio
async def test_startup_closes_the_window_for_registering_overrides() -> None:
    @Injectable
    class Clock:
        pass

    @Module(providers=[Clock], exports=[Clock])
    class AppModule:
        pass

    manager, container = _manager_for(AppModule)

    container.override(Clock, object())
    await manager.startup()

    with pytest.raises(ProviderResolutionError) as raised:
        container.override(Clock, object())

    assert "Clock" in str(raised.value)
    assert "before startup" in str(raised.value)


@pytest.mark.anyio
async def test_a_startup_that_failed_leaves_the_override_window_open() -> None:
    @Injectable
    class Pool:
        def on_application_bootstrap(self) -> None:
            raise RuntimeError("cannot open the pool")

    @Module(providers=[Pool], exports=[Pool])
    class AppModule:
        pass

    manager, container = _manager_for(AppModule)

    with pytest.raises(LifecycleError, match="cannot open the pool"):
        await manager.startup()

    # Nothing the failed startup built survived it, so the application is still one
    # an override can be registered against.
    container.override(Pool, object())
    assert container.has_override(Pool) is True


@pytest.mark.anyio
async def test_each_startup_of_a_restarted_application_takes_its_own_overrides() -> None:
    @Injectable
    class Clock:
        def now(self) -> str:
            return "real"

    @Module(providers=[Clock], exports=[Clock])
    class AppModule:
        pass

    class FakeClock:
        def __init__(self, reading: str) -> None:
            self._reading = reading

        def now(self) -> str:
            return self._reading

    manager, container = _manager_for(AppModule)
    root = container.module_graph.root_key

    container.override(Clock, FakeClock("first cycle"))
    await manager.startup()
    assert cast(Any, container.resolve(Clock, module=root)).now() == "first cycle"
    with pytest.raises(ProviderResolutionError, match="before startup"):
        container.override(Clock, FakeClock("mid-cycle"))

    await manager.shutdown()

    container.override(Clock, FakeClock("second cycle"))
    await manager.startup()
    assert cast(Any, container.resolve(Clock, module=root)).now() == "second cycle"
    with pytest.raises(ProviderResolutionError, match="before startup"):
        container.override(Clock, FakeClock("mid-cycle"))
