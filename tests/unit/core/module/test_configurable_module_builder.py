"""Unit tests for configurable dynamic module generation."""

from __future__ import annotations

from typing import cast

import pytest

from bustan import ConfigurableModuleBuilder, Module
from bustan.core.ioc.container import build_container
from bustan.core.module.builder import ConfigurableModuleDefinition
from bustan.core.module.dynamic import DynamicModule
from bustan.core.module.graph import build_module_graph


def test_configurable_module_builder_generates_dynamic_modules() -> None:
    class ExtraProvider:
        pass

    builder = ConfigurableModuleBuilder[dict[str, str]]().set_class_name("ConfigModule")
    builder.set_extras(providers=(ExtraProvider,))
    ConfigModule, options_token = builder.build()

    dynamic_module = ConfigModule.for_root({"name": "Ada"}, is_global=True)

    assert isinstance(dynamic_module, DynamicModule)
    assert dynamic_module.is_global is True
    assert dynamic_module.exports == (options_token,)
    assert dynamic_module.providers[0] == {"provide": options_token, "use_value": {"name": "Ada"}}
    assert ExtraProvider in dynamic_module.providers


def test_global_dynamic_module_exports_are_visible_without_direct_import() -> None:
    builder = ConfigurableModuleBuilder[dict[str, str]]().set_class_name("ConfigModule")
    ConfigModule, options_token = builder.build()
    global_config = ConfigModule.for_root({"name": "Ada"}, is_global=True)

    @Module()
    class FeatureModule:
        pass

    @Module(imports=[global_config, FeatureModule])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))

    assert container.resolve(options_token, module=FeatureModule) == {"name": "Ada"}


def test_configurable_module_builder_covers_register_and_async_variants() -> None:
    class ConfigFactory:
        pass

    builder = ConfigurableModuleBuilder[dict[str, str]]().set_class_name("ConfigModule")
    ConfigModule, options_token = builder.build()

    registered = ConfigModule.register({"name": "Ada"}, is_global=True)
    factory_module = ConfigModule.for_root_async(use_factory=lambda: {"name": "Ada"}, inject=("DEP",))
    class_module = ConfigModule.for_root_async(use_class=ConfigFactory)
    existing_module = ConfigModule.register_async(use_existing="CONFIG_TOKEN")
    factory_provider = cast(dict[str, object], factory_module.providers[0])

    assert registered.providers[0] == {"provide": options_token, "use_value": {"name": "Ada"}}
    assert registered.is_global is True
    assert factory_provider["provide"] is options_token
    assert factory_provider["inject"] == ("DEP",)
    assert callable(factory_provider["use_factory"])
    assert class_module.providers[0] == {"provide": options_token, "use_class": ConfigFactory}
    assert existing_module.providers[0] == {"provide": options_token, "use_existing": "CONFIG_TOKEN"}

    with pytest.raises(ValueError, match="requires use_factory, use_class, or use_existing"):
        ConfigModule.for_root_async()


def test_configurable_module_definition_base_methods_and_token_reuse_are_stable() -> None:
    builder = ConfigurableModuleBuilder[dict[str, str]]().set_class_name("ConfigModule")
    ConfigModule, options_token = builder.build()
    _, second_token = builder.build()

    assert options_token is second_token

    with pytest.raises(NotImplementedError):
        ConfigurableModuleDefinition.for_root({"name": "Ada"})

    with pytest.raises(NotImplementedError):
        ConfigurableModuleDefinition.register({"name": "Ada"})

    with pytest.raises(NotImplementedError):
        ConfigurableModuleDefinition.for_root_async(use_existing="CONFIG")

    with pytest.raises(NotImplementedError):
        ConfigurableModuleDefinition.register_async(use_existing="CONFIG")
