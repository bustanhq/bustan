"""Integration tests for discovery runtime artifacts and injection."""

from __future__ import annotations

from typing import Any, cast

from starlette.testclient import TestClient

from bustan import Controller, DiscoveryModule, DiscoveryService, Get, Module, create_app


def test_create_app_exposes_public_runtime_artifacts_on_http_server_state() -> None:
    @Controller("/users")
    class UsersController:
        @Get("/")
        def index(self) -> dict[str, str]:
            return {"status": "ok"}

    @Module(imports=[DiscoveryModule], controllers=[UsersController])
    class AppModule:
        pass

    application = create_app(AppModule)
    server = application.get_http_server()

    assert server.state.bustan_application is application
    assert server.state.bustan_container is application.container
    assert server.state.bustan_module_graph is application.module_graph
    assert server.state.bustan_route_contracts == application.route_contracts


def test_discovery_service_is_injectable_during_request_runtime() -> None:
    @Controller("/discovery")
    class DiscoveryController:
        def __init__(self, discovery: DiscoveryService) -> None:
            self._discovery = discovery

        @Get("/")
        def read_discovery(self) -> dict[str, object]:
            return {
                "modules": [entry["module"] for entry in self._discovery.modules()],
                "routes": [entry["path"] for entry in self._discovery.routes()],
            }

    @Module(imports=[DiscoveryModule], controllers=[DiscoveryController])
    class AppModule:
        pass

    with TestClient(cast(Any, create_app(AppModule))) as client:
        response = client.get("/discovery")

    assert response.status_code == 200
    assert response.json() == {
        "modules": ["AppModule", "DiscoveryModule"],
        "routes": ["/discovery"],
    }