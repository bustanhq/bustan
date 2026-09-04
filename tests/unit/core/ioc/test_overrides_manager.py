"""Unit tests for provider override key resolution."""

from __future__ import annotations

from enum import StrEnum

import pytest

from bustan.common.types import ProviderScope
from bustan.core.errors import ProviderResolutionError
from bustan.core.ioc.overrides import OverrideManager
from bustan.core.ioc.registry import Binding, Registry


class RootModule:
    pass


class FeatureModule:
    pass


def test_override_manager_resolves_unique_module_specific_and_ambiguous_keys() -> None:
    registry = Registry()
    registry.register_binding(
        (RootModule, "token"),
        Binding("token", RootModule, "value", object(), ProviderScope.SINGLETON),
    )
    registry.register_binding(
        (RootModule, "shared"),
        Binding("shared", RootModule, "value", object(), ProviderScope.SINGLETON),
    )
    registry.register_binding(
        (FeatureModule, "shared"),
        Binding("shared", FeatureModule, "value", object(), ProviderScope.SINGLETON),
    )
    manager = OverrideManager(registry)

    manager.override("token", "override")
    assert manager.has_override("token") is True
    assert manager.get_override("token") == "override"

    manager.clear_override("token")
    assert manager.has_override("token") is False
    assert manager.get_override("missing") is None

    manager.override("shared", "root-override", module=RootModule)
    assert manager.get_override("shared", module=RootModule) == "root-override"

    with pytest.raises(ProviderResolutionError, match="multiple modules"):
        manager.override("shared", "ambiguous")

    with pytest.raises(ProviderResolutionError, match="not registered in RootModule"):
        manager.override("missing", "value", module=RootModule)


def test_an_override_matches_a_token_by_identity_rather_than_by_equality() -> None:
    # A string enum member equals the bare string it is written as, so an override
    # named with one used to be able to land on the other's binding.
    class Tokens(StrEnum):
        DB = "db"

    registry = Registry()
    registry.register_binding(
        (RootModule, Tokens.DB),
        Binding(Tokens.DB, RootModule, "value", "enum-db", ProviderScope.SINGLETON),
    )
    registry.register_binding(
        (FeatureModule, "db"),
        Binding("db", FeatureModule, "value", "string-db", ProviderScope.SINGLETON),
    )
    manager = OverrideManager(registry)

    manager.override(Tokens.DB, "fake")

    assert manager.get_override(Tokens.DB, module=RootModule) == "fake"
    assert manager.has_override("db", module=FeatureModule) is False
    assert manager.get_override("db") is None

    with pytest.raises(ProviderResolutionError, match="not registered in RootModule"):
        manager.override("db", "value", module=RootModule)


def test_an_override_finds_a_token_equal_to_the_registered_one_of_the_same_type() -> None:
    # Two equal strings are one token however they were spelled, so an override written
    # as a computed string still reaches the binding declared with a literal.
    registry = Registry()
    registry.register_binding(
        (RootModule, "token"),
        Binding("token", RootModule, "value", object(), ProviderScope.SINGLETON),
    )
    manager = OverrideManager(registry)

    manager.override("".join(["to", "ken"]), "override")

    assert manager.get_override("token") == "override"
