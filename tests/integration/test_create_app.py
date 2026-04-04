"""Integration tests for application bootstrap state."""

from starlette.applications import Starlette

from star import Controller, create_app, Get, Injectable, Module


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

    assert isinstance(application, Starlette)
    controller_instance = application.state.star_container.resolve_controller(UserController)

    assert application.state.star_root_module is AppModule
    assert controller_instance.user_service is application.state.star_container.resolve_provider(
        UserService,
        AppModule,
    )
    assert application.state.star_module_graph.root_module is AppModule