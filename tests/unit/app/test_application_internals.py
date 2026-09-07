"""Unit tests for the Application wrapper internals."""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import AsyncMock, patch

import pytest
from starlette.applications import Starlette
from starlette.routing import Route

from bustan import Module, create_app
from bustan.adapters.asgi import AsgiAdapter
from bustan.adapters.starlette import StarletteAdapter
from bustan.app.application import Application, SupportsGracefulShutdown
from bustan.kernel.ioc.container import Container
from bustan.kernel.module.graph import build_module_graph


@pytest.fixture
def app_wrapper() -> Application:
    # Use the new adapter-based initialization
    @Module()
    class Root:
        pass

    graph = build_module_graph(Root)
    container = Container(graph)
    adapter = StarletteAdapter()
    return Application(adapter, container)


def test_application_properties(app_wrapper: Application) -> None:
    # Use public accessors and private ones for internal verification
    assert isinstance(app_wrapper.get_http_server(), Starlette)
    assert isinstance(app_wrapper._container, Container)
    assert app_wrapper._container.module_graph is not None


def test_application_overrides(app_wrapper: Application) -> None:
    class DummyService:
        pass

    from bustan.kernel.ioc.registry import normalize_provider

    container = app_wrapper._container
    module_key = container.module_graph.root_key
    binding = normalize_provider(DummyService, declaring_module=module_key)
    container.registry.register_binding((module_key, DummyService), binding)
    container.registry.set_visibility(module_key, {DummyService: module_key})

    token = DummyService
    value = "overridden"

    # Test overrides directly on the container (where the logic lives now)
    assert not container.has_override(token, module=module_key)
    assert container.get_override(token, module=module_key) is None

    container.override(token, value, module=module_key)
    assert container.has_override(token, module=module_key)
    assert container.get_override(token, module=module_key) == value

    container.clear_override(token, module=module_key)
    assert not container.has_override(token, module=module_key)


def test_application_introspection_properties(app_wrapper: Application) -> None:
    # Routes (public accessor)
    server = app_wrapper.get_http_server()
    server.routes.append(Route("/test", lambda r: None))

    routes = app_wrapper.routes
    assert "/test" in routes
    assert len(routes["/test"]) == 1


@pytest.mark.anyio
async def test_application_asgi_call(app_wrapper: Application) -> None:
    scope = {"type": "http", "path": "/", "method": "GET"}
    calls = []

    async def receive():
        return {"type": "http.request"}

    async def send(message):
        calls.append(message)

    # Delegation to adapter/Starlette
    await app_wrapper(scope, receive, send)
    assert any(c["type"] == "http.response.start" for c in calls)


@pytest.mark.anyio
async def test_closing_an_application_stops_its_server_before_the_teardown_hooks_run() -> None:
    order: list[str] = []

    class RecordingAdapter(StarletteAdapter):
        async def stop(self) -> None:
            order.append("server stopped")
            await super().stop()

    @Module()
    class AppModule:
        def on_application_shutdown(self, signal_name: str | None) -> None:
            order.append(f"hooks ran with {signal_name}")

    application = create_app(AppModule, adapter=RecordingAdapter())
    await application.init()
    await application.close()

    assert order == ["server stopped", "hooks ran with None"]


@pytest.mark.anyio
async def test_closing_an_application_twice_runs_its_teardown_once() -> None:
    shutdowns: list[str] = []

    @Module()
    class AppModule:
        def on_application_shutdown(self, signal_name: str | None) -> None:
            shutdowns.append(str(signal_name))

    application = create_app(AppModule, adapter=StarletteAdapter())
    await application.init()
    await application.close()
    await application.close()

    assert shutdowns == ["None"]


@pytest.mark.anyio
async def test_an_adapter_that_cannot_drain_is_still_stopped_and_torn_down() -> None:
    shutdowns: list[str] = []

    @Module()
    class AppModule:
        def on_application_shutdown(self, signal_name: str | None) -> None:
            shutdowns.append(str(signal_name))

    application = create_app(AppModule, adapter=AsgiAdapter())

    assert not isinstance(application.get_http_adapter(), SupportsGracefulShutdown)

    await application.init()
    await application.close()

    assert shutdowns == ["None"]


@pytest.mark.anyio
async def test_listening_hands_the_adapter_the_drain_window_its_caller_named(
    app_wrapper: Application,
) -> None:
    adapter = cast(Any, app_wrapper.get_http_adapter())
    before = adapter._drain_timeout

    with patch("uvicorn.Server.serve", new_callable=AsyncMock):
        await app_wrapper.listen(0, drain_timeout=0.25)

    assert before != 0.25
    assert adapter._drain_timeout == 0.25
