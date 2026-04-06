"""Integration tests for application bootstrap state."""

from starlette.applications import Starlette

from bustan import Controller, create_app, Get, Injectable, Module


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

    from typing import Any, cast
    from bustan.app.application import Application

    assert isinstance(application, Application)
    assert isinstance(application._starlette_app, Starlette)
    controller_instance = cast(Any, application.container.instantiate_class(UserController, module=AppModule))

    assert application.root_module is AppModule
    assert (
        controller_instance.user_service
        is application.container.resolve(
            UserService,
            module=AppModule,
        )
    )
    assert cast(Any, application.module_graph).root_module is AppModule
