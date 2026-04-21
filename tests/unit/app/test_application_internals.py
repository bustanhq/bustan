"""Unit tests for the Application wrapper internals."""

from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.routing import Route

from bustan import Module
from bustan.app.application import Application
from bustan.core.ioc.container import Container
from bustan.core.module.graph import build_module_graph
from bustan.platform.http.adapters.starlette_adapter import StarletteAdapter


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

    from bustan.core.ioc.registry import normalize_provider

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
