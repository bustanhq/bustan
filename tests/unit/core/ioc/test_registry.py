"""Unit tests for registry binding normalization and storage."""

from __future__ import annotations

from typing import cast

import pytest

from bustan.common.types import ProviderScope
from bustan.core.ioc.registry import Binding, Registry, normalize_provider


class AppModule:
    pass


def test_normalize_provider_covers_class_factory_value_existing_and_errors() -> None:
    class Service:
        pass

    class Replacement:
        pass

    assert normalize_provider(Service, AppModule) == Binding(
        token=Service,
        declaring_module=AppModule,
        resolver_kind="class",
        target=Service,
        scope=ProviderScope.SINGLETON,
    )
    assert normalize_provider(
        {"provide": "client", "use_class": Replacement, "scope": "request"},
        AppModule,
    ) == Binding(
        token="client",
        declaring_module=AppModule,
        resolver_kind="class",
        target=Replacement,
        scope=ProviderScope.REQUEST,
    )
    factory_binding = normalize_provider(
        {"provide": "factory", "use_factory": lambda: "ok", "inject": ["dep"]},
        AppModule,
    )
    factory_target = cast(tuple[object, tuple[object, ...]], factory_binding.target)
    assert factory_binding.token == "factory"
    assert factory_binding.declaring_module is AppModule
    assert factory_binding.resolver_kind == "factory"
    assert callable(factory_target[0])
    assert factory_target[1] == ("dep",)
    assert factory_binding.scope is ProviderScope.SINGLETON
    assert normalize_provider(
        {"provide": "value", "use_value": 1, "scope": "transient"},
        AppModule,
    ) == Binding(
        token="value",
        declaring_module=AppModule,
        resolver_kind="value",
        target=1,
        scope=ProviderScope.SINGLETON,
    )
    assert normalize_provider(
        {"provide": "alias", "use_existing": Service},
        AppModule,
    ) == Binding(
        token="alias",
        declaring_module=AppModule,
        resolver_kind="existing",
        target=Service,
        scope=ProviderScope.TRANSIENT,
    )

    with pytest.raises(TypeError, match="provide"):
        normalize_provider({"use_value": 1}, AppModule)

    with pytest.raises(TypeError, match="one of"):
        normalize_provider({"provide": "broken"}, AppModule)

    with pytest.raises(TypeError, match="Invalid provider definition"):
        normalize_provider(123, AppModule)


def test_registry_stores_bindings_visibility_and_controller_ownership() -> None:
    registry = Registry()
    binding = Binding("token", AppModule, "value", 1, ProviderScope.SINGLETON)

    registry.register_binding((AppModule, "token"), binding)
    registry.set_visibility(AppModule, {"token": AppModule})
    registry.register_controller(AppModule, AppModule)

    assert registry.get_binding((AppModule, "token")) is binding
    assert registry.module_visibility[AppModule] == {"token": AppModule}
    assert registry.controller_modules[AppModule] is AppModule
