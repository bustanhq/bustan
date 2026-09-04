"""Unit tests for registry binding normalization and storage."""

from __future__ import annotations

from typing import cast

import pytest

from bustan.common.types import ProviderScope
from bustan.core.errors import InvalidProviderError
from bustan.core.ioc.registry import Binding, Registry, normalize_provider


class AppModule:
    pass


def test_normalize_provider_covers_class_factory_value_and_existing_forms() -> None:
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
        {"provide": "value", "use_value": 1},
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


@pytest.mark.xfail(
    strict=True,
    reason="an explicit scope on a use_value provider is dropped instead of refused",
)
def test_normalize_provider_refuses_a_scope_it_cannot_honour() -> None:
    # A provider definition is a contract, so every key in it is either honoured or
    # refused. A value binding is inherently one shared object, so the only honest
    # answer to a narrower scope written beside it is to reject the definition;
    # dropping the key hands the author a singleton they explicitly did not ask for.
    with pytest.raises(InvalidProviderError) as ignored_scope:
        normalize_provider({"provide": "value", "use_value": 1, "scope": "transient"}, AppModule)

    message = str(ignored_scope.value)
    assert "scope" in message
    assert "value" in message


@pytest.mark.xfail(
    strict=True,
    reason="malformed provider definitions escape as a bare TypeError",
)
def test_normalize_provider_reports_malformed_definitions_as_provider_errors() -> None:
    # Every rejection at this boundary is a Bustan error naming the module that
    # declared the provider and the key at fault, because the author's next action
    # is to edit that module and a builtin exception tells them neither. Each form
    # is normalized before anything is asserted so that one report names every
    # definition still rejected the wrong way, not only the first.
    missing_provide = _rejection({"use_value": 1})
    missing_target = _rejection({"provide": "broken"})
    not_a_provider = _rejection(123)

    rejections = (missing_provide, missing_target, not_a_provider)
    assert [type(rejected) for rejected in rejections] == [InvalidProviderError] * 3
    assert all("AppModule" in str(rejected) for rejected in rejections)
    assert "provide" in str(missing_provide)
    assert "use_value" in str(missing_target)
    assert "123" in str(not_a_provider)


def test_registry_stores_bindings_visibility_and_controller_ownership() -> None:
    registry = Registry()
    binding = Binding("token", AppModule, "value", 1, ProviderScope.SINGLETON)

    registry.register_binding((AppModule, "token"), binding)
    registry.set_visibility(AppModule, {"token": AppModule})
    registry.register_controller(AppModule, AppModule)

    assert registry.get_binding((AppModule, "token")) is binding
    assert registry.module_visibility[AppModule] == {"token": AppModule}
    assert registry.controller_modules[AppModule] is AppModule


def _rejection(definition: object) -> Exception | None:
    try:
        normalize_provider(definition, AppModule)
    except Exception as rejected:
        return rejected
    return None
