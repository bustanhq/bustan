"""Unit tests for module graph discovery and validation."""

from typing import cast

import pytest

from bustan import Controller, DynamicModule, Get, Global, Injectable, Module
from bustan.core.errors import (
    ExportViolationError,
    InvalidControllerError,
    InvalidModuleError,
    ModuleCycleError,
    RouteDefinitionError,
)
from bustan.core.module.graph import build_module_graph


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
    assert graph.controllers_for(UsersModule) == (UserController,)


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


def test_global_decorator_marks_existing_module_metadata() -> None:
    @Global()
    @Module()
    class SharedModule:
        pass

    graph = build_module_graph(SharedModule)

    assert graph.get_node(SharedModule).metadata.is_global is True


def test_visibility_names_the_declaring_module_through_a_re_export() -> None:
    # A re-export passes a token on; it does not declare it. Visibility must name the
    # module that holds the binding, or the graph promises what nothing can deliver.
    @Injectable
    class Repository:
        pass

    @Module(providers=[Repository], exports=[Repository])
    class DataModule:
        pass

    @Module(imports=[DataModule], exports=[Repository])
    class SharedModule:
        pass

    @Module(imports=[SharedModule])
    class AppModule:
        pass

    graph = build_module_graph(AppModule)

    assert graph.get_node(AppModule).visibility[Repository] is DataModule
    assert graph.get_node(SharedModule).visibility[Repository] is DataModule
    assert Repository in graph.available_providers_for(AppModule)


def test_available_providers_include_global_exports() -> None:
    @Injectable
    class GlobalService:
        pass

    @Module(providers=[GlobalService], exports=[GlobalService], is_global=True)
    class GlobalModule:
        pass

    @Module()
    class ConsumerModule:
        pass

    @Module(imports=[GlobalModule, ConsumerModule])
    class AppModule:
        pass

    graph = build_module_graph(AppModule)

    assert GlobalService in graph.available_providers_for(ConsumerModule)
    assert graph.get_node(ConsumerModule).visibility[GlobalService] is GlobalModule


def test_a_module_may_export_a_globally_visible_token() -> None:
    # Export validation reads the same visibility the resolver does, so a token a module
    # can resolve is a token it may export.
    @Injectable
    class GlobalService:
        pass

    @Module(providers=[GlobalService], exports=[GlobalService], is_global=True)
    class GlobalModule:
        pass

    @Module(exports=[GlobalService])
    class FacadeModule:
        pass

    @Module(imports=[GlobalModule, FacadeModule])
    class AppModule:
        pass

    graph = build_module_graph(AppModule)

    assert graph.get_node(FacadeModule).visibility[GlobalService] is GlobalModule


def test_a_local_provider_shadows_an_imported_export_of_the_same_token() -> None:
    @Module(providers=[{"provide": "config", "use_value": "imported"}], exports=["config"])
    class SettingsModule:
        pass

    @Module(
        imports=[SettingsModule],
        providers=[{"provide": "config", "use_value": "local"}],
    )
    class AppModule:
        pass

    graph = build_module_graph(AppModule)

    assert graph.get_node(AppModule).visibility["config"] is AppModule


def test_build_module_graph_refuses_two_global_modules_exporting_one_token() -> None:
    @Global()
    @Module(providers=[{"provide": "config", "use_value": "first"}], exports=["config"])
    class FirstGlobalModule:
        pass

    @Global()
    @Module(providers=[{"provide": "config", "use_value": "second"}], exports=["config"])
    class SecondGlobalModule:
        pass

    # Neither global module is imported beside the other, so nothing but the global rule
    # can catch the collision.
    @Module(imports=[FirstGlobalModule])
    class LeftModule:
        pass

    @Module(imports=[SecondGlobalModule])
    class RightModule:
        pass

    @Module(imports=[LeftModule, RightModule])
    class AppModule:
        pass

    with pytest.raises(InvalidModuleError) as failure:
        build_module_graph(AppModule)

    message = str(failure.value)
    assert "FirstGlobalModule" in message
    assert "SecondGlobalModule" in message
    assert "'config'" in message


def test_build_module_graph_refuses_two_imports_exporting_one_token() -> None:
    @Module(providers=[{"provide": "config", "use_value": "left"}], exports=["config"])
    class LeftModule:
        pass

    @Module(providers=[{"provide": "config", "use_value": "right"}], exports=["config"])
    class RightModule:
        pass

    @Module(imports=[LeftModule, RightModule])
    class AppModule:
        pass

    with pytest.raises(InvalidModuleError) as failure:
        build_module_graph(AppModule)

    message = str(failure.value)
    assert "LeftModule" in message
    assert "RightModule" in message
    assert "'config'" in message


def test_two_imports_re_exporting_one_origin_are_not_ambiguous() -> None:
    # Both paths lead to the same binding, so there is nothing to choose between.
    @Injectable
    class Repository:
        pass

    @Module(providers=[Repository], exports=[Repository])
    class DataModule:
        pass

    @Module(imports=[DataModule], exports=[Repository])
    class ReadModule:
        pass

    @Module(imports=[DataModule], exports=[Repository])
    class WriteModule:
        pass

    @Module(imports=[ReadModule, WriteModule])
    class AppModule:
        pass

    graph = build_module_graph(AppModule)

    assert graph.get_node(AppModule).visibility[Repository] is DataModule


def test_build_module_graph_rejects_exporting_a_module_class() -> None:
    @Injectable
    class UserService:
        pass

    @Module(providers=[UserService], exports=[UserService])
    class UsersModule:
        pass

    @Module(imports=[UsersModule], exports=[UsersModule])
    class CoreModule:
        pass

    with pytest.raises(InvalidModuleError, match="exports the module UsersModule"):
        build_module_graph(CoreModule)


def test_build_module_graph_rejects_exporting_a_dynamic_module() -> None:
    @Module()
    class SettingsModule:
        pass

    dynamic_settings = DynamicModule(
        SettingsModule, providers=({"provide": "config", "use_value": "value"},)
    )

    @Module(imports=[dynamic_settings], exports=[dynamic_settings])
    class CoreModule:
        pass

    with pytest.raises(InvalidModuleError, match="exports the module SettingsModule"):
        build_module_graph(CoreModule)


def test_a_cycle_through_a_dynamic_module_reports_the_path() -> None:
    class ConfigModule:
        pass

    dynamic_config = DynamicModule(ConfigModule)

    @Module(imports=[dynamic_config])
    class FeatureModule:
        pass

    # ConfigModule is decorated after the dynamic registration exists, so the same
    # DynamicModule object is reached again through FeatureModule.
    Module(imports=[FeatureModule])(ConfigModule)

    @Module(imports=[dynamic_config])
    class AppModule:
        pass

    with pytest.raises(ModuleCycleError) as failure:
        build_module_graph(AppModule)

    message = str(failure.value)
    assert "AppModule -> ConfigModule[0] -> FeatureModule -> ConfigModule (dynamic)" in message
    assert "DynamicModule(module=" not in message


def test_a_global_module_may_export_a_token_another_global_module_declares() -> None:
    # The token is already visible everywhere, so the second export adds nothing and
    # names no second origin to collide with.
    @Injectable
    class Clock:
        pass

    @Global()
    @Module(providers=[Clock], exports=[Clock])
    class TimeModule:
        pass

    @Global()
    @Module(exports=[Clock])
    class FacadeModule:
        pass

    @Module(imports=[TimeModule, FacadeModule])
    class AppModule:
        pass

    graph = build_module_graph(AppModule)

    assert graph.get_node(AppModule).visibility[Clock] is TimeModule
    assert graph.get_node(FacadeModule).visibility[Clock] is TimeModule


def test_build_module_graph_rejects_importing_an_undecorated_class() -> None:
    class PlainModule:
        pass

    @Module(imports=[PlainModule])
    class AppModule:
        pass

    with pytest.raises(InvalidModuleError, match="is not a decorated module"):
        build_module_graph(AppModule)
