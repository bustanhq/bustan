"""Unit tests for the Application wrapper internals."""

from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.routing import Route

from bustan import Module
from bustan.app.application import Application
from bustan.core.ioc.container import Container
from bustan.core.module.graph import build_module_graph


@pytest.fixture
def app_wrapper() -> Application:
    starlette_app = Starlette()
    # Create a minimal valid module graph using a DECORATED module
    @Module()
    class Root:
        pass

    graph = build_module_graph(Root)
    container = Container(graph)
    return Application(starlette_app, container)


def test_application_properties(app_wrapper: Application) -> None:
    assert isinstance(app_wrapper.starlette_app, Starlette)
    assert isinstance(app_wrapper.container, Container)
    assert app_wrapper.module_graph is not None


def test_application_overrides(app_wrapper: Application) -> None:
    class DummyService:
        pass

    from bustan.core.ioc.registry import normalize_provider

    module_key = app_wrapper.container.module_graph.root_key
    binding = normalize_provider(DummyService, declaring_module=module_key)
    app_wrapper.container.registry.register_binding((module_key, DummyService), binding)
    app_wrapper.container.registry.set_visibility(module_key, {DummyService: module_key})

    token = DummyService
    value = "overridden"

    assert not app_wrapper.has_override(token, module=module_key)
    assert app_wrapper.get_override(token, module=module_key) is None

    app_wrapper.override(token, value, module=module_key)
    assert app_wrapper.has_override(token, module=module_key)
    assert app_wrapper.get_override(token, module=module_key) == value

    app_wrapper.clear_override(token, module=module_key)
    assert not app_wrapper.has_override(token, module=module_key)


def test_application_introspection_properties(app_wrapper: Application) -> None:
    # Controllers
    assert isinstance(app_wrapper.controllers, dict)

    # Routes
    app_wrapper.starlette_app.routes.append(Route("/test", lambda r: None))
    routes = app_wrapper.routes
    assert "/test" in routes
    assert len(routes["/test"]) == 1

    # Module instances
    assert isinstance(app_wrapper.module_instances, dict)


@pytest.mark.anyio
async def test_application_asgi_call(app_wrapper: Application) -> None:
    scope = {"type": "http", "path": "/", "method": "GET"}
    calls = []

    async def receive():
        return {"type": "http.request"}

    async def send(message):
        calls.append(message)

    await app_wrapper(scope, receive, send)
    assert any(c["type"] == "http.response.start" for c in calls)
