"""Integration tests for application bootstrap state."""

from typing import Any, cast
from starlette.applications import Starlette
import pytest

from bustan import Controller, create_app, Get, Injectable, Module
from bustan.app.application import Application
from bustan.errors import RouteDefinitionError
from bustan.platform.http.adapter import CompiledAdapterRoute
from bustan.platform.http.adapters.starlette_adapter import StarletteAdapter


def test_create_app_returns_a_starlette_application_with_module_graph_state() -> None:
    @Injectable
    class UserService:
        pass

    @Controller("/users")
    class UserController:
        def __init__(self, user_service: UserService) -> None:
            self.user_service = user_service

        @Get("/")
        def list_users(self) -> list[dict[str, str]]:
            return [{"name": "Moses"}]

    @Module(controllers=[UserController], providers=[UserService], exports=[UserService])
    class AppModule:
        pass

    application = create_app(AppModule)

    assert isinstance(application, Application)
    # Check underlying server via public accessor
    assert isinstance(application.get_http_server(), Starlette)
    
    # Use private container for internal instantiation checks in integration tests
    controller_instance = cast(Any, application._container.instantiate_class(UserController, module=AppModule))

    # Check internal module graph state for the root module
    assert application._container.module_graph.root_module is AppModule
    assert (
        controller_instance.user_service
        is application._container.resolve(
            UserService,
            module=AppModule,
        )
    )
    # Check internal module graph state
    assert application._container.module_graph.root_module is AppModule


def test_create_app_fails_fast_for_controller_handler_without_route_metadata() -> None:
    @Controller("/users")
    class UsersController:
        def list_users(self) -> list[dict[str, str]]:
            return [{"name": "Ada"}]

    @Module(controllers=[UsersController])
    class AppModule:
        pass

    with pytest.raises(RouteDefinitionError, match="UsersController.list_users.*missing an HTTP route decorator"):
        create_app(AppModule)


def test_create_app_registers_compiled_adapter_routes_in_deterministic_order() -> None:
    class RecordingStarletteAdapter(StarletteAdapter):
        def __init__(self) -> None:
            super().__init__()
            self.registered_routes: list[CompiledAdapterRoute] = []

        def register_routes(self, routes: list[CompiledAdapterRoute]) -> None:
            self.registered_routes = list(routes)
            super().register_routes(routes)

    @Controller("/zeta")
    class ZetaController:
        @Get("/")
        def index(self) -> dict[str, str]:
            return {"controller": "zeta"}

    @Controller("/alpha")
    class AlphaController:
        @Get("/")
        def index(self) -> dict[str, str]:
            return {"controller": "alpha"}

    @Module(controllers=[ZetaController, AlphaController])
    class AppModule:
        pass

    adapter = RecordingStarletteAdapter()
    create_app(AppModule, adapter=adapter)

    assert [compiled_route.path for compiled_route in adapter.registered_routes] == ["/zeta", "/alpha"]
    assert all(isinstance(compiled_route, CompiledAdapterRoute) for compiled_route in adapter.registered_routes)
