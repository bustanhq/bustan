"""Unit tests for route compilation edge cases."""

import pytest

from star import Controller, Get, Module
from star.container import build_container
from star.errors import ParameterBindingError, RouteDefinitionError
from star.module_graph import build_module_graph
from star.routing import compile_routes


def test_compile_routes_rejects_duplicate_application_routes() -> None:
    @Controller("/users")
    class UsersController:
        @Get("/")
        def list_users(self) -> list[dict[str, str]]:
            return [{"name": "Ada"}]

    @Controller("/users")
    class ProfilesController:
        @Get("/")
        def list_profiles(self) -> list[dict[str, str]]:
            return [{"name": "Moses"}]

    @Module(controllers=[UsersController, ProfilesController])
    class AppModule:
        pass

    module_graph = build_module_graph(AppModule)
    container = build_container(module_graph)

    with pytest.raises(RouteDefinitionError, match="Duplicate application route GET /users"):
        compile_routes(module_graph, container)


def test_compile_routes_rejects_variadic_handler_parameters() -> None:
    @Controller("/users")
    class UsersController:
        @Get("/{user_id}")
        def read_user(self, *user_ids: str) -> dict[str, str]:
            return {"ids": ",".join(user_ids)}

    @Module(controllers=[UsersController])
    class AppModule:
        pass

    module_graph = build_module_graph(AppModule)
    container = build_container(module_graph)

    with pytest.raises(ParameterBindingError, match="unsupported variadic parameter"):
        compile_routes(module_graph, container)