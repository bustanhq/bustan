"""Unit tests for route compilation edge cases."""

import pytest

from star import controller, get, module
from star.container import build_container
from star.errors import ParameterBindingError, RouteDefinitionError
from star.module_graph import build_module_graph
from star.routing import compile_routes


def test_compile_routes_rejects_duplicate_application_routes() -> None:
    @controller("/users")
    class UsersController:
        @get("/")
        def list_users(self) -> list[dict[str, str]]:
            return [{"name": "Ada"}]

    @controller("/users")
    class ProfilesController:
        @get("/")
        def list_profiles(self) -> list[dict[str, str]]:
            return [{"name": "Moses"}]

    @module(controllers=[UsersController, ProfilesController])
    class AppModule:
        pass

    module_graph = build_module_graph(AppModule)
    container = build_container(module_graph)

    with pytest.raises(RouteDefinitionError, match="Duplicate application route GET /users"):
        compile_routes(module_graph, container)


def test_compile_routes_rejects_variadic_handler_parameters() -> None:
    @controller("/users")
    class UsersController:
        @get("/{user_id}")
        def read_user(self, *user_ids: str) -> dict[str, str]:
            return {"ids": ",".join(user_ids)}

    @module(controllers=[UsersController])
    class AppModule:
        pass

    module_graph = build_module_graph(AppModule)
    container = build_container(module_graph)

    with pytest.raises(ParameterBindingError, match="unsupported variadic parameter"):
        compile_routes(module_graph, container)