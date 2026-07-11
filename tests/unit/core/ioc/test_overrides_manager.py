"""Unit tests for provider override key resolution."""

from __future__ import annotations

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
