"""Unit tests for registry binding normalization and storage."""

from __future__ import annotations

from collections.abc import Iterator
from enum import StrEnum
from typing import cast

import pytest

from bustan import Injectable
from bustan.common.constants import BUSTAN_PROVIDER_ATTR
from bustan.common.types import ProviderScope
from bustan.core.errors import InvalidProviderError
from bustan.core.ioc.registry import (
    Binding,
    BindingTable,
    Registry,
    TokenMap,
    normalize_provider,
)


class AppModule:
    pass


class FeatureModule:
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


class Service:
    pass


class DurableByInstanceMethod:
    def get_durable_context_key(self, request: object) -> str:
        return "tenant"


class DurableByClassMethod:
    @classmethod
    def get_durable_context_key(cls, request: object) -> str:
        return "tenant"


class DurableByStaticMethod:
    @staticmethod
    def get_durable_context_key(request: object) -> str:
        return "tenant"


def _factory() -> str:
    return "built"


_USE_ENTRIES: dict[str, object] = {
    "use_class": Service,
    "use_factory": _factory,
    "use_value": 1,
    "use_existing": Service,
}


def test_normalize_provider_binds_an_undecorated_subclass_under_its_own_identity() -> None:
    # Metadata written on a base class describes that class. Reading it through the
    # subclass bound the parent under the parent's token, so the subclass was never
    # constructed and the name it was registered under could not be resolved.
    @Injectable(scope=ProviderScope.REQUEST)
    class Base:
        pass

    class Derived(Base):
        pass

    assert normalize_provider(Base, AppModule) == Binding(
        token=Base,
        declaring_module=AppModule,
        resolver_kind="class",
        target=Base,
        scope=ProviderScope.REQUEST,
    )
    assert normalize_provider(Derived, AppModule) == Binding(
        token=Derived,
        declaring_module=AppModule,
        resolver_kind="class",
        target=Derived,
        scope=ProviderScope.SINGLETON,
    )


def test_normalize_provider_refuses_a_class_carrying_foreign_provider_metadata() -> None:
    class Handwritten:
        pass

    setattr(Handwritten, BUSTAN_PROVIDER_ATTR, {"token": Service, "use_class": Service})

    with pytest.raises(InvalidProviderError, match="@Injectable"):
        normalize_provider(Handwritten, AppModule)


def test_normalize_provider_reads_a_single_token_inject_as_a_mistake() -> None:
    # A string is a sequence of characters, so "dep" used to normalize to three tokens
    # named 'd', 'e' and 'p' and only failed much later, at resolution.
    with pytest.raises(InvalidProviderError, match="inject") as refusal:
        normalize_provider(
            {"provide": "f", "use_factory": _factory, "inject": "dep"},
            AppModule,
        )

    assert "AppModule" in str(refusal.value)


def test_normalize_provider_refuses_a_durable_lifetime_it_cannot_partition() -> None:
    # A durable instance is selected by a key derived before any instance exists, so the
    # hook has to be reachable on the class itself and only a class binding can carry it.
    assert (
        normalize_provider(
            {"provide": "tenant", "use_class": DurableByClassMethod, "scope": "durable"},
            AppModule,
        ).scope
        is ProviderScope.DURABLE
    )
    assert (
        normalize_provider(
            {"provide": "tenant", "use_class": DurableByStaticMethod, "scope": "durable"},
            AppModule,
        ).scope
        is ProviderScope.DURABLE
    )

    with pytest.raises(InvalidProviderError, match="classmethod or a staticmethod"):
        normalize_provider(
            {"provide": "tenant", "use_class": DurableByInstanceMethod, "scope": "durable"},
            AppModule,
        )

    with pytest.raises(InvalidProviderError, match="only a class can carry"):
        normalize_provider(
            {"provide": "tenant", "use_factory": _factory, "scope": "durable"},
            AppModule,
        )

    with pytest.raises(InvalidProviderError, match="scope"):
        normalize_provider(
            {"provide": "tenant", "use_value": {"tenant": "a"}, "scope": "durable"},
            AppModule,
        )


def test_injectable_durable_class_needs_an_unbound_context_key_hook() -> None:
    decorated = Injectable(scope=ProviderScope.DURABLE)(
        type("DurableService", (DurableByInstanceMethod,), {})
    )

    with pytest.raises(InvalidProviderError, match="classmethod or a staticmethod"):
        normalize_provider(decorated, AppModule)


def test_every_valid_dict_provider_shape_is_accepted() -> None:
    accepted = (
        {"provide": "t", "use_class": Service},
        {"provide": "t", "use_class": Service, "scope": "request"},
        {"provide": "t", "use_class": Service, "scope": ProviderScope.TRANSIENT},
        {"provide": "t", "use_factory": _factory},
        {"provide": "t", "use_factory": _factory, "inject": ()},
        {"provide": "t", "use_factory": _factory, "inject": ["dep", Service]},
        {"provide": "t", "use_factory": Service, "scope": "transient"},
        {"provide": "t", "use_value": None},
        {"provide": "t", "use_existing": Service},
        {"provide": Service, "use_existing": "other"},
    )

    for definition in accepted:
        assert normalize_provider(definition, AppModule).declaring_module is AppModule


def test_every_invalid_dict_provider_shape_is_refused_naming_the_module_and_key() -> None:
    # The breadth is the point: a validator that only rejects the shapes someone thought
    # to write down is how 'inject' beside 'use_class' stayed silent for a whole release.
    shapes = tuple(_invalid_dict_provider_shapes())
    assert len(shapes) > 60

    unreported: list[str] = []
    for definition, expected_key in shapes:
        try:
            normalize_provider(definition, AppModule)
        except InvalidProviderError as refusal:
            message = str(refusal)
            if "AppModule" not in message or expected_key not in message:
                unreported.append(f"{definition!r} -> {message}")
        except Exception as escaped:  # noqa: BLE001
            unreported.append(f"{definition!r} -> escaped as {type(escaped).__name__}: {escaped}")
        else:
            unreported.append(f"{definition!r} -> accepted")

    assert unreported == []


def _invalid_dict_provider_shapes() -> Iterator[tuple[dict[str, object], str]]:
    """Generate malformed provider definitions paired with the key each must name."""

    for use_key, target in _USE_ENTRIES.items():
        yield {use_key: target}, "provide"

        for unknown in ("useClass", "provider", "Scope", "inject_tokens", "1"):
            yield {"provide": "t", use_key: target, unknown: 1}, unknown

        for other_key, other_target in _USE_ENTRIES.items():
            if other_key != use_key:
                yield {"provide": "t", use_key: target, other_key: other_target}, other_key

        if use_key != "use_factory":
            yield {"provide": "t", use_key: target, "inject": ["dep"]}, "inject"

        if use_key not in ("use_class", "use_factory"):
            for scope in ProviderScope:
                yield {"provide": "t", use_key: target, "scope": scope.value}, "scope"
        else:
            for scope in ("Request", "bogus", "", None, 1, ["request"], {"scope": 1}):
                yield {"provide": "t", use_key: target, "scope": scope}, "scope"

    for empty in ({}, {"scope": "request"}, {"provide": "t"}, {"provide": "t", "inject": ()}):
        yield dict(empty), "provide" if "provide" not in empty else "use_value"

    for unhashable in ({"name": "x"}, ["x"], bytearray(b"x"), {1: {2: 3}}):
        yield {"provide": unhashable, "use_value": 1}, "provide"

    for not_a_class in (Service(), _factory, 42, None, "Service", (Service,)):
        yield {"provide": "t", "use_class": not_a_class}, "use_class"

    for not_callable in (42, None, "factory", (), Service()):
        yield {"provide": "t", "use_factory": not_callable}, "use_factory"

    for bad_inject in ("dep", b"dep", 42, None, Service()):
        yield {"provide": "t", "use_factory": _factory, "inject": bad_inject}, "inject"

    yield (
        {"provide": "t", "use_class": DurableByInstanceMethod, "scope": "durable"},
        "get_durable_context_key",
    )
    yield {"provide": "t", "use_factory": _factory, "scope": "durable"}, "use_factory"


def test_a_use_class_definition_takes_the_lifetime_its_target_declares() -> None:
    # Binding a class under an interface token does not change what its instances are
    # safe to hold, so a definition naming no lifetime takes the class's own. Reading
    # the default instead made a per-request class a process-wide singleton, and the
    # first caller's state was then served to every later one.
    @Injectable(scope=ProviderScope.REQUEST)
    class PerRequestAudit:
        pass

    binding = normalize_provider({"provide": "audit", "use_class": PerRequestAudit}, AppModule)

    assert binding.scope is ProviderScope.REQUEST


def test_a_use_class_definition_may_narrow_a_declared_lifetime_but_never_widen_it() -> None:
    @Injectable(scope=ProviderScope.REQUEST)
    class PerRequestAudit:
        pass

    narrowed = normalize_provider(
        {"provide": "audit", "use_class": PerRequestAudit, "scope": ProviderScope.TRANSIENT},
        AppModule,
    )

    assert narrowed.scope is ProviderScope.TRANSIENT

    with pytest.raises(InvalidProviderError, match="never widen it") as refusal:
        normalize_provider(
            {"provide": "audit", "use_class": PerRequestAudit, "scope": "singleton"}, AppModule
        )

    assert "PerRequestAudit" in str(refusal.value)
    assert "the class declares request scope" in str(refusal.value)


def test_a_use_class_definition_whose_target_declares_nothing_keeps_the_default() -> None:
    # An undecorated class declares no lifetime of its own, and neither does an
    # undecorated subclass of one that does.
    @Injectable(scope=ProviderScope.REQUEST)
    class Base:
        pass

    class Derived(Base):
        pass

    assert (
        normalize_provider({"provide": "t", "use_class": Service}, AppModule).scope
        is ProviderScope.SINGLETON
    )
    assert (
        normalize_provider({"provide": "t", "use_class": Derived}, AppModule).scope
        is ProviderScope.SINGLETON
    )


def test_token_map_keeps_equal_tokens_of_different_types_apart() -> None:
    class Tokens(StrEnum):
        DB = "db"

    # The pairs are written as a sequence because a dict literal would already have
    # collapsed them onto one entry, which is the whole defect.
    table: TokenMap[str] = TokenMap([(Tokens.DB, "enum"), ("db", "string")])
    table[True] = "bool"
    table[1] = "int"

    assert table[Tokens.DB] == "enum"
    assert table["db"] == "string"
    assert (table[True], table[1]) == ("bool", "int")
    assert list(table) == [Tokens.DB, "db", True, 1]
    # A plain dict would report these as the same mapping, which is the collapse this
    # mapping exists to prevent.
    assert table != {"db": "string", 1: "int"}
    assert table == TokenMap([(Tokens.DB, "enum"), ("db", "string"), (True, "bool"), (1, "int")])

    assert table != "not a mapping"
    assert repr(table).startswith("TokenMap({<Tokens.DB: 'db'>: 'enum', 'db': 'string'")

    del table[Tokens.DB]

    assert Tokens.DB not in table
    assert table["db"] == "string"


def test_binding_table_keys_a_binding_by_its_module_and_token_identity() -> None:
    class Tokens(StrEnum):
        DB = "db"

    enum_binding = Binding(Tokens.DB, AppModule, "value", "enum", ProviderScope.SINGLETON)
    string_binding = Binding("db", FeatureModule, "value", "string", ProviderScope.SINGLETON)
    table = BindingTable()
    table[(AppModule, Tokens.DB)] = enum_binding
    table[(FeatureModule, "db")] = string_binding

    assert table[(AppModule, Tokens.DB)] is enum_binding
    assert (AppModule, "db") not in table
    assert list(table) == [(AppModule, Tokens.DB), (FeatureModule, "db")]
    assert len(table) == 2
    assert repr(table).startswith("BindingTable({")

    del table[(AppModule, Tokens.DB)]

    assert list(table) == [(FeatureModule, "db")]


def test_registry_tells_two_equal_tokens_of_different_types_apart() -> None:
    class Tokens(StrEnum):
        DB = "db"

    registry = Registry()
    enum_binding = Binding(Tokens.DB, AppModule, "value", "enum-db", ProviderScope.SINGLETON)
    registry.register_binding((AppModule, Tokens.DB), enum_binding)
    registry.set_visibility(AppModule, {Tokens.DB: AppModule})

    assert registry.get_binding((AppModule, Tokens.DB)) is enum_binding
    assert registry.get_binding((AppModule, "db")) is None
    assert registry.module_visibility[AppModule].get("db") is None
