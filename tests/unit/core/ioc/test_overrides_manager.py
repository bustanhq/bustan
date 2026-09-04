"""Unit tests for provider override key resolution and the bootstrap-only rule."""

from __future__ import annotations

from enum import StrEnum

import pytest

from bustan.common.types import ProviderScope
from bustan.core.errors import ProviderResolutionError
from bustan.core.ioc.overrides import OverrideManager
from bustan.core.ioc.planning.plan import ContainerPlan
from bustan.core.ioc.registry import Binding, Registry
from bustan.core.ioc.scopes import ScopeManager
from bustan.core.module.dynamic import ModuleInstanceKey

# Nothing in this module has a constructor to plan: every binding under test is a
# value, so the reach of an override is the binding itself.
EMPTY_PLAN = ContainerPlan(constructions={})


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
    scopes = ScopeManager()

    manager.override("token", "override", plan=EMPTY_PLAN, scopes=scopes)
    assert manager.has_override("token") is True
    assert manager.get_override("token") == "override"

    manager.clear_override("token", plan=EMPTY_PLAN, scopes=scopes)
    assert manager.has_override("token") is False
    assert manager.get_override("missing") is None

    manager.override("shared", "root-override", module=RootModule, plan=EMPTY_PLAN, scopes=scopes)
    assert manager.get_override("shared", module=RootModule) == "root-override"

    with pytest.raises(ProviderResolutionError, match="more than one module"):
        manager.override("shared", "ambiguous", plan=EMPTY_PLAN, scopes=scopes)

    with pytest.raises(ProviderResolutionError, match="not registered in RootModule"):
        manager.override("missing", "value", module=RootModule, plan=EMPTY_PLAN, scopes=scopes)


def test_the_ambiguity_error_names_the_parameter_that_settles_it() -> None:
    # The parameter named has to be one the caller can actually pass, or the message
    # sends them looking for a keyword that does not exist.
    registry = Registry()
    for module in (RootModule, FeatureModule):
        registry.register_binding(
            (module, "shared"),
            Binding("shared", module, "value", object(), ProviderScope.SINGLETON),
        )
    manager = OverrideManager(registry)

    with pytest.raises(ProviderResolutionError) as raised:
        manager.override("shared", "fake", plan=EMPTY_PLAN, scopes=ScopeManager())

    message = str(raised.value)
    assert "RootModule" in message
    assert "FeatureModule" in message
    assert "'module'" in message


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
    scopes = ScopeManager()

    manager.override(Tokens.DB, "fake", plan=EMPTY_PLAN, scopes=scopes)

    assert manager.get_override(Tokens.DB, module=RootModule) == "fake"
    assert manager.has_override("db", module=FeatureModule) is False
    assert manager.get_override("db") is None

    with pytest.raises(ProviderResolutionError, match="not registered in RootModule"):
        manager.override("db", "value", module=RootModule, plan=EMPTY_PLAN, scopes=scopes)


def test_an_override_finds_a_token_equal_to_the_registered_one_of_the_same_type() -> None:
    # Two equal strings are one token however they were spelled, so an override written
    # as a computed string still reaches the binding declared with a literal.
    registry = Registry()
    registry.register_binding(
        (RootModule, "token"),
        Binding("token", RootModule, "value", object(), ProviderScope.SINGLETON),
    )
    manager = OverrideManager(registry)

    manager.override("".join(["to", "ken"]), "override", plan=EMPTY_PLAN, scopes=ScopeManager())

    assert manager.get_override("token") == "override"


def test_a_module_class_names_the_dynamic_registration_that_declares_the_token() -> None:
    # A dynamic registration is keyed by an instance key the caller never holds, so the
    # class it registers is the only spelling available to them.
    registration = ModuleInstanceKey(FeatureModule, "0")
    registry = Registry()
    registry.register_binding(
        (registration, "config"),
        Binding("config", registration, "value", "prod", ProviderScope.SINGLETON),
    )
    manager = OverrideManager(registry)

    manager.override("config", "fake", module=FeatureModule, plan=EMPTY_PLAN, scopes=ScopeManager())

    assert manager.get_override("config", module=FeatureModule) == "fake"
    assert manager.get_override("config", module=registration) == "fake"


def test_two_registrations_of_one_module_declaring_a_token_are_genuinely_ambiguous() -> None:
    registry = Registry()
    for instance_id in ("0", "1"):
        registration = ModuleInstanceKey(FeatureModule, instance_id)
        registry.register_binding(
            (registration, "config"),
            Binding("config", registration, "value", instance_id, ProviderScope.SINGLETON),
        )
    manager = OverrideManager(registry)

    with pytest.raises(ProviderResolutionError, match="FeatureModule\\[0\\], FeatureModule\\[1\\]"):
        manager.override(
            "config", "fake", module=FeatureModule, plan=EMPTY_PLAN, scopes=ScopeManager()
        )

    # Naming the registration itself settles it, which is what the message asks for.
    manager.override(
        "config",
        "fake",
        module=ModuleInstanceKey(FeatureModule, "1"),
        plan=EMPTY_PLAN,
        scopes=ScopeManager(),
    )
    assert manager.get_override("config", module=ModuleInstanceKey(FeatureModule, "1")) == "fake"


def test_an_override_of_a_singleton_binding_becomes_the_cached_singleton() -> None:
    # The lifecycle runs its hooks over what the container holds, so a replacement that
    # is not held there is initialized and destroyed by nobody.
    registry = Registry()
    registry.register_binding(
        (RootModule, "db"),
        Binding("db", RootModule, "class", RootModule, ProviderScope.SINGLETON),
    )
    registry.register_binding(
        (RootModule, "per-request"),
        Binding("per-request", RootModule, "class", RootModule, ProviderScope.REQUEST),
    )
    manager = OverrideManager(registry)
    scopes = ScopeManager()
    fake = object()

    manager.override("db", fake, plan=EMPTY_PLAN, scopes=scopes)
    manager.override("per-request", object(), plan=EMPTY_PLAN, scopes=scopes)

    assert scopes.singletons[(RootModule, "db")] is fake
    assert (RootModule, "per-request") not in scopes.singletons

    manager.clear_override("db", plan=EMPTY_PLAN, scopes=scopes)
    assert (RootModule, "db") not in scopes.singletons


def test_overrides_are_refused_once_the_application_has_started() -> None:
    registry = Registry()
    registry.register_binding(
        (RootModule, "clock"),
        Binding("clock", RootModule, "value", object(), ProviderScope.SINGLETON),
    )
    manager = OverrideManager(registry)
    scopes = ScopeManager()
    manager.override("clock", "fake", plan=EMPTY_PLAN, scopes=scopes)

    manager.mark_started()
    assert manager.started is True

    with pytest.raises(ProviderResolutionError) as raised:
        manager.override("clock", "later", plan=EMPTY_PLAN, scopes=scopes)
    assert "'clock'" in str(raised.value)
    assert "before startup" in str(raised.value)

    with pytest.raises(ProviderResolutionError, match="before startup"):
        manager.clear_override("clock", plan=EMPTY_PLAN, scopes=scopes)

    # Reading what is already registered stays available while the application runs.
    assert manager.has_override("clock") is True
    assert manager.get_override("clock") == "fake"

    manager.mark_stopped()
    manager.override("clock", "later", plan=EMPTY_PLAN, scopes=scopes)
    assert manager.get_override("clock") == "later"
