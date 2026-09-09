"""Unit tests for the server lifespan that starts and stops the module graph."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from bustan import Injectable, Module, create_app
from bustan.app.application import entered_application_scope, owning_application
from bustan.app.lifespan import build_lifespan
from bustan.kernel.ioc.container import build_container
from bustan.kernel.lifecycle.manager import LifecycleManager
from bustan.kernel.module.graph import build_module_graph


@pytest.mark.anyio
async def test_the_lifespan_names_the_application_only_while_a_stage_runs() -> None:
    named: list[object] = []

    @Injectable()
    class Pool:
        pass

    @Module(providers=[Pool], exports=[Pool])
    class RootModule:
        def on_application_bootstrap(self) -> None:
            named.append(scope_manager.active_application.get())

        def on_application_shutdown(self, signal: str | None) -> None:
            named.append(scope_manager.active_application.get())

    application = create_app(RootModule)
    lifecycle_manager = application.lifecycle_manager
    assert lifecycle_manager is not None
    scope_manager = application.container.scope_manager
    seated = owning_application(lifecycle_manager)

    async with build_lifespan(lifecycle_manager)(application.get_http_server()):
        assert named == [seated]
        # Startup is over, so nothing is holding the application open: a lifespan that
        # kept it named would be doing so from whichever task resumed it.
        assert scope_manager.active_application.get() is None

    assert named == [seated, seated]
    assert scope_manager.active_application.get() is None
    assert seated is not None
    assert seated.http_application is application


@pytest.mark.anyio
async def test_a_lifespan_over_a_container_outside_an_application_starts_the_graph() -> None:
    events: list[str] = []

    @Module()
    class RootModule:
        def on_application_bootstrap(self) -> None:
            events.append("bootstrap")

        def on_module_destroy(self) -> None:
            events.append("destroy")

    module_graph = build_module_graph(RootModule)
    container = build_container(module_graph)
    lifecycle_manager = LifecycleManager(module_graph, container)
    server = SimpleNamespace(state=SimpleNamespace())

    assert owning_application(lifecycle_manager) is None

    async with build_lifespan(lifecycle_manager)(server):
        assert events == ["bootstrap"]
        assert container.scope_manager.active_application.get() is None

    assert events == ["bootstrap", "destroy"]
    assert server.state.bustan_module_instances is not None


def test_a_scope_entered_with_no_application_names_none() -> None:
    @Module()
    class RootModule:
        pass

    container = build_container(build_module_graph(RootModule))

    with entered_application_scope(None):
        assert container.scope_manager.active_application.get() is None
