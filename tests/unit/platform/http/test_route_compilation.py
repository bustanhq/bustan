"""Unit tests for route compilation edge cases."""

import pytest

from bustan import Controller, Get, Module
from bustan.core.ioc.container import build_container
from bustan.errors import ParameterBindingError, RouteDefinitionError
from bustan.core.module.graph import build_module_graph
from bustan.platform.http.routing import compile_routes


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


def test_compile_routes_rejects_host_routing_for_direct_starlette_compilation() -> None:
    @Controller("/users", host="api.example.test")
    class UsersController:
        @Get("/")
        def list_users(self) -> list[dict[str, str]]:
            return [{"name": "Ada"}]

    @Module(controllers=[UsersController])
    class AppModule:
        pass

    module_graph = build_module_graph(AppModule)
    container = build_container(module_graph)

    with pytest.raises(RouteDefinitionError, match="host routing"):
        compile_routes(module_graph, container)
