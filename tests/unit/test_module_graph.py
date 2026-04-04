"""Unit tests for module graph discovery and validation."""

import pytest
from typing import cast

from star import Controller, Get, Injectable, Module
from star.errors import (
    ExportViolationError,
    InvalidControllerError,
    InvalidModuleError,
    ModuleCycleError,
    RouteDefinitionError,
)
from star.module_graph import build_module_graph


def test_build_module_graph_preserves_import_order_and_visibility() -> None:
    @Injectable
    class UserService:
        pass

    @Injectable
    class HiddenService:
        pass

    @Controller("/users")
    class UserController:
        @Get("/")
        def list_users(self) -> list[dict[str, str]]:
            return [{"name": "Moses"}]

    @Module(
        controllers=[UserController],
        providers=[UserService, HiddenService],
        exports=[UserService],
    )
    class UsersModule:
        pass

    @Injectable
    class AuthService:
        pass

    @Module(providers=[AuthService], exports=[AuthService])
    class AuthModule:
        pass

    @Module(imports=[UsersModule, AuthModule])
    class AppModule:
        pass

    graph = build_module_graph(AppModule)
    assert [node.module.__name__ for node in graph.nodes] == [
        "AppModule",
        "UsersModule",
        "AuthModule",
    ]

    app_node = graph.get_node(AppModule)
    assert app_node.imported_exports[UsersModule] == frozenset({UserService})
    assert app_node.imported_exports[AuthModule] == frozenset({AuthService})
    assert app_node.available_providers == frozenset({UserService, AuthService})


def test_build_module_graph_rejects_invalid_imports() -> None:
    invalid_import = cast(type[object], object())

    @Module(imports=[invalid_import])
    class AppModule:
        pass

    with pytest.raises(InvalidModuleError, match="imports .* is not a decorated module"):
        build_module_graph(AppModule)


def test_build_module_graph_rejects_non_decorated_controller() -> None:
    class PlainController:
        pass

    @Module(controllers=[PlainController])
    class AppModule:
        pass

    with pytest.raises(InvalidControllerError, match="not decorated with @Controller"):
        build_module_graph(AppModule)


def test_build_module_graph_rejects_export_outside_provider_set() -> None:
    @Injectable
    class UserService:
        pass

    @Injectable
    class ExportedService:
        pass

    @Module(providers=[UserService], exports=[ExportedService])
    class AppModule:
        pass

    with pytest.raises(ExportViolationError, match="exports"):
        build_module_graph(AppModule)


def test_build_module_graph_detects_cycles_with_the_cycle_path() -> None:
    class AppModule:
        pass

    class AuthModule:
        pass

    Module(imports=[AuthModule])(AppModule)
    Module(imports=[AppModule])(AuthModule)

    with pytest.raises(ModuleCycleError, match="AppModule -> AuthModule -> AppModule"):
        build_module_graph(AppModule)


def test_build_module_graph_rejects_duplicate_controller_routes() -> None:
    @Controller("/users")
    class UserController:
        @Get("/profile")
        def read_profile(self) -> None:
            return None

        @Get("/profile")
        def read_profile_again(self) -> None:
            return None

    @Module(controllers=[UserController])
    class AppModule:
        pass

    with pytest.raises(RouteDefinitionError, match="duplicate route GET /users/profile"):
        build_module_graph(AppModule)