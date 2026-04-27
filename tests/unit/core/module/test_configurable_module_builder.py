"""Unit tests for configurable dynamic module generation."""

from __future__ import annotations

from bustan import ConfigurableModuleBuilder, Module
from bustan.core.ioc.container import build_container
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
