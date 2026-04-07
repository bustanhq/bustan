"""Integration tests for application bootstrap state."""

from typing import Any, cast
from starlette.applications import Starlette
from bustan import Controller, create_app, Get, Injectable, Module
from bustan.app.application import Application


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

    assert application._root_module is AppModule
    assert (
        controller_instance.user_service
        is application._container.resolve(
            UserService,
            module=AppModule,
        )
    )
    # Check internal module graph state
    assert application._container.module_graph.root_module is AppModule
