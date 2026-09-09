"""Unit tests for registry binding normalization and storage."""

from __future__ import annotations

from collections.abc import Iterator
from enum import StrEnum
from types import MappingProxyType
from typing import cast

import pytest

from bustan import ClassProvider, ExistingProvider, FactoryProvider, Injectable, ValueProvider
from bustan.common.constants import BUSTAN_PROVIDER_ATTR
from bustan.common.types import ProviderDefinition, ProviderScope
from bustan.kernel.errors import InvalidProviderError
from bustan.kernel.ioc.registry import (
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
        ClassProvider(provide="client", use_class=Replacement, scope=ProviderScope.REQUEST),
        AppModule,
    ) == Binding(
        token="client",
        declaring_module=AppModule,
        resolver_kind="class",
        target=Replacement,
        scope=ProviderScope.REQUEST,
    )
    factory_binding = normalize_provider(
        FactoryProvider(provide="factory", use_factory=lambda: "ok", inject=("dep",)),
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
        ValueProvider(provide="value", use_value=1),
        AppModule,
    ) == Binding(
        token="value",
        declaring_module=AppModule,
        resolver_kind="value",
        target=1,
        scope=ProviderScope.SINGLETON,
    )
    assert normalize_provider(
        ExistingProvider(provide="alias", use_existing=Service),
        AppModule,
    ) == Binding(
        token="alias",
        declaring_module=AppModule,
        resolver_kind="existing",
        target=Service,
        scope=ProviderScope.TRANSIENT,
    )


def test_normalize_provider_reports_malformed_definitions_as_provider_errors() -> None:
    # Every rejection at this boundary is a Bustan error naming the module that
    # declared the provider and the key at fault, because the author's next action
    # is to edit that module and a builtin exception tells them neither. Each form
    # is normalized before anything is asserted so that one report names every
    # definition still rejected the wrong way, not only the first.
    not_a_provider = _rejection(123)
    nothing_at_all = _rejection(None)

    rejections = (not_a_provider, nothing_at_all)
    assert [type(rejected) for rejected in rejections] == [InvalidProviderError] * 2
    assert all("AppModule" in str(rejected) for rejected in rejections)
    assert "123" in str(not_a_provider)
    assert "None" in str(nothing_at_all)


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

# Each target key the dict spelling could name, beside the value type that binds what a
# dict naming it declared. The refusal is judged against this, so a caller reading it is
# reading the arm that replaces the declaration they wrote.
_DICT_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("use_class", "ClassProvider"),
    ("use_factory", "FactoryProvider"),
    ("use_value", "ValueProvider"),
    ("use_existing", "ExistingProvider"),
)


def test_a_mapping_is_refused_naming_the_value_type_that_replaces_it() -> None:
    # The dict was a second spelling of these same four declarations, and a second
    # spelling is far more expensive to withdraw once applications are written against
    # it. What is refused is therefore the shape rather than any malformed instance of
    # it, and the refusal carries the whole of the author's next edit.
    for use_key, replacement in _DICT_REPLACEMENTS:
        written_as_a_dict: dict[str, object] = dict(provide="t")
        written_as_a_dict[use_key] = _USE_ENTRIES[use_key]
        # The dict the refusal quotes back is the one it was handed, its two values
        # standing in as X and Y, so the expectation is derived rather than transcribed.
        quoted = ", ".join(
            f'"{key}": {placeholder}'
            for key, placeholder in zip(written_as_a_dict, "XY", strict=True)
        )

        with pytest.raises(InvalidProviderError) as refusal:
            normalize_provider(written_as_a_dict, AppModule)

        assert str(refusal.value) == (
            f"Invalid provider in AppModule: a dict is no longer a provider. "
            f"Replace {{{quoted}}} with {replacement}(provide=X, {use_key}=Y)"
        )


def test_a_mapping_naming_no_target_is_still_refused_as_the_shape_it_is() -> None:
    # A dict that named nothing to bind has no arm of its own to be told about, and a
    # mapping that is not a dict is the same declaration written in another container.
    # Neither is a provider, so neither is read for a token before it is refused.
    for empty in (dict[str, object](), MappingProxyType(dict(provide="t"))):
        with pytest.raises(InvalidProviderError, match="a dict is no longer a provider") as refusal:
            normalize_provider(empty, AppModule)

        assert "ClassProvider(provide=X, use_class=Y)" in str(refusal.value)


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
    # named 'd', 'e' and 'p' and only failed much later, at resolution. The field is
    # declared as a tuple, so this is now a type error where it is written and the
    # suppression is what lets the test reach the refusal a caller from unchecked code
    # still gets.
    with pytest.raises(InvalidProviderError, match="inject") as refusal:
        normalize_provider(
            FactoryProvider(
                provide="f",
                use_factory=_factory,
                inject="dep",  # ty: ignore[invalid-argument-type]
            ),
            AppModule,
        )

    assert "AppModule" in str(refusal.value)


def test_normalize_provider_refuses_a_durable_lifetime_it_cannot_partition() -> None:
    # A durable instance is selected by a key derived before any instance exists, so the
    # hook has to be reachable on the class itself and only a class binding can carry it.
    assert (
        normalize_provider(
            ClassProvider(
                provide="tenant", use_class=DurableByClassMethod, scope=ProviderScope.DURABLE
            ),
            AppModule,
        ).scope
        is ProviderScope.DURABLE
    )
    assert (
        normalize_provider(
            ClassProvider(
                provide="tenant", use_class=DurableByStaticMethod, scope=ProviderScope.DURABLE
            ),
            AppModule,
        ).scope
        is ProviderScope.DURABLE
    )

    with pytest.raises(InvalidProviderError, match="classmethod or a staticmethod"):
        normalize_provider(
            ClassProvider(
                provide="tenant", use_class=DurableByInstanceMethod, scope=ProviderScope.DURABLE
            ),
            AppModule,
        )

    with pytest.raises(InvalidProviderError, match="only a class can carry"):
        normalize_provider(
            FactoryProvider(provide="tenant", use_factory=_factory, scope=ProviderScope.DURABLE),
            AppModule,
        )


def test_injectable_durable_class_needs_an_unbound_context_key_hook() -> None:
    decorated = Injectable(scope=ProviderScope.DURABLE)(
        type("DurableService", (DurableByInstanceMethod,), {})
    )

    with pytest.raises(InvalidProviderError, match="classmethod or a staticmethod"):
        normalize_provider(decorated, AppModule)


def test_every_valid_provider_declaration_is_accepted() -> None:
    accepted = (
        ClassProvider(provide="t", use_class=Service),
        ClassProvider(provide="t", use_class=Service, scope=ProviderScope.REQUEST),
        ClassProvider(provide="t", use_class=Service, scope=ProviderScope.TRANSIENT),
        FactoryProvider(provide="t", use_factory=_factory),
        FactoryProvider(provide="t", use_factory=_factory, inject=()),
        FactoryProvider(provide="t", use_factory=_factory, inject=("dep", Service)),
        FactoryProvider(provide="t", use_factory=Service, scope=ProviderScope.TRANSIENT),
        ValueProvider(provide="t", use_value=None),
        ExistingProvider(provide="t", use_existing=Service),
        ExistingProvider(provide=Service, use_existing="other"),
    )

    for definition in accepted:
        assert normalize_provider(definition, AppModule).declaring_module is AppModule


def test_every_invalid_provider_declaration_is_refused_naming_the_module_and_key() -> None:
    # The breadth is the point: a validator that only rejects the shapes someone thought
    # to write down is how a silently ignored 'inject' stayed silent for a whole release.
    # Every field of every arm is reachable from code the type checker never saw, so each
    # is generated rather than chosen.
    shapes = tuple(_invalid_provider_declarations())
    assert len(shapes) > 20

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


def _invalid_provider_declarations() -> Iterator[tuple[ProviderDefinition, str]]:
    """Generate provider declarations whose fields hold what the field cannot mean.

    Every declaration here is a type error where it is written, which is the point of
    the value types. The container still has to refuse each one by name, because a
    caller that reaches it from unchecked code gets no such warning, and each is
    suppressed so this test can reach that refusal.
    """

    for unhashable in ({"name": "x"}, ["x"], bytearray(b"x"), {1: {2: 3}}):
        yield ValueProvider(provide=unhashable, use_value=1), "provide"

    for not_a_class in (Service(), _factory, 42, None, "Service", (Service,)):
        yield (
            ClassProvider(provide="t", use_class=not_a_class),  # ty: ignore[invalid-argument-type]
            "use_class",
        )

    for not_callable in (42, None, "factory", (), Service()):
        yield (
            FactoryProvider(
                provide="t",
                use_factory=not_callable,  # ty: ignore[invalid-argument-type]
            ),
            "use_factory",
        )

    for bad_inject in ("dep", b"dep", 42, None, Service()):
        yield (
            FactoryProvider(
                provide="t",
                use_factory=_factory,
                inject=bad_inject,  # ty: ignore[invalid-argument-type]
            ),
            "inject",
        )

    # Only the two arms that carry a lifetime can name one that is not a lifetime.
    for bad_scope in ("Request", "bogus", "", 1, ["request"]):
        yield (
            ClassProvider(
                provide="t",
                use_class=Service,
                scope=bad_scope,  # ty: ignore[invalid-argument-type]
            ),
            "scope",
        )
        yield (
            FactoryProvider(
                provide="t",
                use_factory=_factory,
                scope=bad_scope,  # ty: ignore[invalid-argument-type]
            ),
            "scope",
        )

    yield (
        ClassProvider(provide="t", use_class=DurableByInstanceMethod, scope=ProviderScope.DURABLE),
        "get_durable_context_key",
    )
    yield (
        FactoryProvider(provide="t", use_factory=_factory, scope=ProviderScope.DURABLE),
        "use_factory",
    )


def test_a_use_class_definition_takes_the_lifetime_its_target_declares() -> None:
    # Binding a class under an interface token does not change what its instances are
    # safe to hold, so a definition naming no lifetime takes the class's own. Reading
    # the default instead made a per-request class a process-wide singleton, and the
    # first caller's state was then served to every later one.
    @Injectable(scope=ProviderScope.REQUEST)
    class PerRequestAudit:
        pass

    binding = normalize_provider(
        ClassProvider(provide="audit", use_class=PerRequestAudit), AppModule
    )

    assert binding.scope is ProviderScope.REQUEST


def test_a_use_class_definition_may_narrow_a_declared_lifetime_but_never_widen_it() -> None:
    @Injectable(scope=ProviderScope.REQUEST)
    class PerRequestAudit:
        pass

    narrowed = normalize_provider(
        ClassProvider(provide="audit", use_class=PerRequestAudit, scope=ProviderScope.TRANSIENT),
        AppModule,
    )

    assert narrowed.scope is ProviderScope.TRANSIENT

    with pytest.raises(InvalidProviderError, match="never widen it") as refusal:
        normalize_provider(
            ClassProvider(
                provide="audit", use_class=PerRequestAudit, scope=ProviderScope.SINGLETON
            ),
            AppModule,
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
        normalize_provider(ClassProvider(provide="t", use_class=Service), AppModule).scope
        is ProviderScope.SINGLETON
    )
    assert (
        normalize_provider(ClassProvider(provide="t", use_class=Derived), AppModule).scope
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
