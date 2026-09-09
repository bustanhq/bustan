"""Unit tests for the discovery addon surface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from bustan import (
    ConfigModule,
    Controller,
    DiscoveryModule,
    DiscoveryService,
    DynamicModule,
    Get,
    Injectable,
    InjectionToken,
    Module,
    ValueProvider,
    create_app,
)
from bustan.kernel.utils import _display_name, _qualname

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

# A value that would be a secret in a real application. Every assertion below looks for
# it in the whole of a reported surface, because a value that reaches a report reaches
# it in whichever field the report happened to render it in.
_FAKE_CREDENTIAL = "orchard-quay-fake-credential"


@dataclass(frozen=True, slots=True)
class _TokenBuiltFromAValue:
    """A provider token that is an object, so its repr holds what it was built from."""

    credential: str


def _names(field: object) -> tuple[str, ...]:
    """Read a report field that holds a tuple of names, which every row reports as one."""

    assert isinstance(field, tuple)
    return tuple(str(name) for name in field)


def test_discovery_service_enumerates_modules_providers_and_routes() -> None:
    @Injectable
    class GreetingService:
        pass

    @Controller("/greetings")
    class GreetingController:
        @Get("/")
        def read_greeting(self) -> dict[str, str]:
            return {"message": "hello"}

    @Module(
        imports=[DiscoveryModule],
        controllers=[GreetingController],
        providers=[GreetingService],
        exports=[GreetingService],
    )
    class AppModule:
        pass

    application = create_app(AppModule)
    discovery = application.get(DiscoveryService)

    modules = discovery.modules()
    providers = discovery.providers()
    routes = discovery.routes()

    assert [entry["module"] for entry in modules] == ["AppModule", "DiscoveryModule"]
    assert modules[0]["controllers"] == ("GreetingController",)
    assert [entry["token"] for entry in providers] == [
        "GreetingService",
        "DiscoveryService",
        "ModuleRef",
    ]
    assert len(routes) == 1
    assert routes[0]["controller"] == "GreetingController"
    assert routes[0]["path"] == "/greetings"


def test_discovery_service_preserves_deterministic_order() -> None:
    @Injectable
    class ZetaService:
        pass

    @Injectable
    class AlphaService:
        pass

    @Controller("/zeta")
    class ZetaController:
        @Get("/")
        def index(self) -> dict[str, str]:
            return {"controller": "zeta"}

    @Controller("/alpha")
    class AlphaController:
        @Get("/")
        def index(self) -> dict[str, str]:
            return {"controller": "alpha"}

    @Module(
        imports=[DiscoveryModule],
        controllers=[ZetaController, AlphaController],
        providers=[ZetaService, AlphaService],
        exports=[ZetaService, AlphaService],
    )
    class AppModule:
        pass

    discovery = create_app(AppModule).get(DiscoveryService)

    assert discovery.modules() == discovery.modules()
    assert [entry["token"] for entry in discovery.providers_for_module(AppModule)] == [
        "AlphaService",
        "ZetaService",
    ]
    assert [entry["path"] for entry in discovery.routes()] == ["/alpha", "/zeta"]


def test_discovery_service_does_not_mutate_container_state() -> None:
    @Injectable
    class GreetingService:
        pass

    @Controller("/greetings")
    class GreetingController:
        @Get("/")
        def read_greeting(self) -> dict[str, str]:
            return {"message": "hello"}

    @Module(
        imports=[DiscoveryModule],
        controllers=[GreetingController],
        providers=[GreetingService],
        exports=[GreetingService],
    )
    class AppModule:
        pass

    application = create_app(AppModule)
    discovery = application.get(DiscoveryService)
    binding_count = len(application.container.registry.bindings)
    routes_before = application.snapshot_routes()

    discovery.modules()
    discovery.providers()
    discovery.routes()

    assert len(application.container.registry.bindings) == binding_count
    assert not application.container.has_override(GreetingService)
    assert application.snapshot_routes() == routes_before


def test_modules_names_a_configured_module_without_the_values_it_was_built_with(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A configuration module is built with the whole environment it resolved.

    Any application code may call this surface - a health endpoint, an admin page, a
    support dump - so a module reached through a factory is named here and never
    described.
    """

    env_file = tmp_path / "discovery.env"
    env_file.write_text(f"DISCOVERY_DATABASE_PASSWORD={_FAKE_CREDENTIAL}\n", encoding="utf-8")
    monkeypatch.delenv("DISCOVERY_DATABASE_PASSWORD", raising=False)

    @Module(imports=[DiscoveryModule, ConfigModule.for_root(env_file=str(env_file))])
    class AppModule:
        pass

    modules = create_app(AppModule).get(DiscoveryService).modules()

    assert _FAKE_CREDENTIAL not in repr(modules)
    root = next(entry for entry in modules if entry["module"] == "AppModule")
    configured = [name for name in _names(root["imports"]) if name.startswith("_ConfigModuleBase")]
    assert configured == ["_ConfigModuleBase (dynamic)[0]"]
    # The import and the row for the module it names are the same name, so a reader can
    # follow one to the other.
    assert configured[0] in [entry["module"] for entry in modules]


def test_provider_and_export_rows_name_a_token_without_the_value_it_was_built_from() -> None:
    """A token is the name a provider is bound by, and a name is all that is printed.

    A token given a name prints that name. A token that is an object has no name of its
    own, and printing the object would print whatever it was built from, so the report
    names the kind of token it is instead.
    """

    @Module()
    class SettingsModule:
        pass

    named_token = InjectionToken[str]("DISCOVERY_CREDENTIAL")
    object_token = _TokenBuiltFromAValue(_FAKE_CREDENTIAL)
    settings = DynamicModule(
        module=SettingsModule,
        providers=(
            ValueProvider(provide=named_token, use_value=_FAKE_CREDENTIAL),
            ValueProvider(provide=object_token, use_value=_FAKE_CREDENTIAL),
        ),
        exports=(named_token, object_token),
    )

    @Module(imports=[DiscoveryModule, settings])
    class AppModule:
        pass

    discovery = create_app(AppModule).get(DiscoveryService)
    modules = discovery.modules()
    providers = discovery.providers()

    assert _FAKE_CREDENTIAL not in repr(modules)
    assert _FAKE_CREDENTIAL not in repr(providers)
    settings_entry = next(
        entry for entry in modules if str(entry["module"]).startswith("SettingsModule")
    )
    named = (
        "<_TokenBuiltFromAValue>",
        "InjectionToken('DISCOVERY_CREDENTIAL')",
    )
    assert settings_entry["providers"] == named
    assert settings_entry["exports"] == named


def test_two_registrations_of_one_module_are_told_apart_by_name() -> None:
    """Two registrations differ in what they were built with, which is not printed."""

    @Module()
    class FeatureModule:
        pass

    first = DynamicModule(
        module=FeatureModule,
        providers=(ValueProvider(provide="feature.first", use_value=_FAKE_CREDENTIAL),),
    )
    second = DynamicModule(
        module=FeatureModule,
        providers=(ValueProvider(provide="feature.second", use_value=_FAKE_CREDENTIAL),),
    )

    @Module(imports=[DiscoveryModule, first, second])
    class AppModule:
        pass

    modules = create_app(AppModule).get(DiscoveryService).modules()

    assert _FAKE_CREDENTIAL not in repr(modules)
    registrations = [
        str(entry["module"])
        for entry in modules
        if str(entry["module"]).startswith("FeatureModule")
    ]
    assert registrations == ["FeatureModule (dynamic)[0]", "FeatureModule (dynamic)[1]"]
    root = next(entry for entry in modules if entry["module"] == "AppModule")
    assert set(_names(root["imports"])) == {"DiscoveryModule", *registrations}


def test_a_registration_is_named_by_its_module_before_it_has_been_compiled() -> None:
    """The name of a declaration is the guard standing behind the report's own.

    A report names a module by the key the graph compiled it to, so a declaration only
    reaches a name when something asks for one directly, such as a message about a
    module that never compiled. A declaration holds the providers it was built with, so
    it is named there rather than printed too.
    """

    @Module()
    class SettingsModule:
        pass

    registration = DynamicModule(
        module=SettingsModule,
        providers=(ValueProvider(provide="settings.credential", use_value=_FAKE_CREDENTIAL),),
    )

    assert _display_name(registration) == "SettingsModule (dynamic)"
    assert _qualname(registration).endswith(".SettingsModule (dynamic)")
    assert _FAKE_CREDENTIAL not in _display_name(registration)
    assert _FAKE_CREDENTIAL not in _qualname(registration)
