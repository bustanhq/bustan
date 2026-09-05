"""Unit tests for compiled module validation helpers."""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from typing import cast

import pytest

from bustan import APP_GUARD, Module
from bustan.common.types import ProviderScope
from bustan.core.errors import InvalidModuleError, InvalidProviderError
from bustan.core.ioc.registry import Binding
from bustan.core.module.compiler import (
    MULTI_PROVIDER_TOKENS,
    CompiledModuleDef,
    expand_module_input,
    validate_module_compiled,
)
from bustan.core.module.dynamic import DynamicModule, ModuleInstanceKey
from bustan.core.module.metadata import ModuleMetadata


def test_expand_module_input_merges_dynamic_modules_and_validates_undecorated_inputs() -> None:
    class ImportedModule:
        pass

    class ExtraImportedModule:
        pass

    class ControllerA:
        pass

    class ControllerB:
        pass

    class ProviderA:
        pass

    class ProviderB:
        pass

    @Module(
        imports=[ImportedModule],
        controllers=[ControllerA],
        providers=[ProviderA],
        exports=[ProviderA],
    )
    class BaseModule:
        pass

    compiled = expand_module_input(
        DynamicModule(
            module=BaseModule,
            imports=(ExtraImportedModule,),
            controllers=(ControllerB,),
            providers=(ProviderB,),
            exports=(ProviderA, ProviderB),
            is_global=True,
        ),
        instance_id="dyn-1",
    )

    assert compiled.key == ModuleInstanceKey(BaseModule, "dyn-1")
    assert compiled.metadata.imports == (ImportedModule, ExtraImportedModule)
    assert compiled.metadata.controllers == (ControllerA, ControllerB)
    assert compiled.metadata.providers == (ProviderA, ProviderB)
    assert compiled.metadata.exports == (ProviderA, ProviderB)
    assert compiled.metadata.is_global is True

    static_compiled = expand_module_input(BaseModule, instance_id="ignored")
    assert static_compiled.key is BaseModule
    assert static_compiled.metadata == ModuleMetadata(
        imports=(ImportedModule,),
        controllers=(ControllerA,),
        providers=(ProviderA,),
        exports=(ProviderA,),
        is_global=False,
    )

    class PlainModule:
        pass

    with pytest.raises(InvalidModuleError, match="valid base module"):
        expand_module_input(DynamicModule(module=PlainModule), instance_id="dyn-2")

    with pytest.raises(InvalidModuleError, match="not a decorated module"):
        expand_module_input(PlainModule, instance_id="plain")


def test_validate_module_compiled_rejects_duplicates_and_invalid_providers() -> None:
    class ProviderA:
        pass

    compiled = CompiledModuleDef(
        key=ProviderA,
        module=ProviderA,
        metadata=ModuleMetadata(
            imports=(), controllers=(), providers=(ProviderA, ProviderA), exports=()
        ),
    )
    with pytest.raises(InvalidModuleError, match="duplicate entries in providers"):
        validate_module_compiled(compiled)

    compiled = CompiledModuleDef(
        key=ProviderA,
        module=ProviderA,
        metadata=ModuleMetadata(
            imports=(ProviderA, ProviderA), controllers=(), providers=(), exports=()
        ),
    )
    with pytest.raises(InvalidModuleError, match="duplicate entries in imports"):
        validate_module_compiled(compiled)

    compiled = CompiledModuleDef(
        key=ProviderA,
        module=ProviderA,
        metadata=ModuleMetadata(
            imports=(),
            controllers=(),
            providers=({"provide": "broken"},),
            exports=(),
        ),
    )
    with pytest.raises(InvalidProviderError, match="Invalid provider"):
        validate_module_compiled(compiled)


def test_validate_module_compiled_separates_duplicate_tokens_from_aliasing_ones() -> None:
    # A string enum member and the bare string it equals hash alike, so the container
    # would key both onto one binding. Reporting that as a duplicate hides the cause,
    # which is that the two declarations are not actually the same token.
    class Tokens(StrEnum):
        DB = "db"

    aliased = CompiledModuleDef(
        key=_OwnerModule,
        module=_OwnerModule,
        metadata=ModuleMetadata(
            providers=(
                {"provide": Tokens.DB, "use_value": "from-enum"},
                {"provide": "db", "use_value": "from-string"},
            )
        ),
    )
    with pytest.raises(InvalidProviderError, match="are equal but are not the same token"):
        validate_module_compiled(aliased)

    repeated = CompiledModuleDef(
        key=_OwnerModule,
        module=_OwnerModule,
        metadata=ModuleMetadata(
            providers=(
                {"provide": "db", "use_value": 1},
                {"provide": "db", "use_value": 2},
            )
        ),
    )
    with pytest.raises(InvalidModuleError, match="duplicate entries in providers"):
        validate_module_compiled(repeated)


def test_validate_module_compiled_names_the_module_and_the_key_it_refused() -> None:
    compiled = CompiledModuleDef(
        key=_OwnerModule,
        module=_OwnerModule,
        metadata=ModuleMetadata(providers=({"provide": "http", "use_factory": 42},)),
    )

    with pytest.raises(InvalidProviderError) as refusal:
        validate_module_compiled(compiled)

    message = str(refusal.value)
    assert "_OwnerModule" in message
    assert "use_factory" in message


def test_one_entry_for_a_multi_provider_token_is_bound_exactly_as_it_was_written() -> None:
    class Guard:
        pass

    compiled = CompiledModuleDef(
        key=_OwnerModule,
        module=_OwnerModule,
        metadata=ModuleMetadata(providers=({"provide": APP_GUARD, "use_class": Guard},)),
    )

    bindings = validate_module_compiled(compiled)

    assert len(bindings) == 1
    assert bindings[0].token is APP_GUARD
    assert bindings[0].resolver_kind == "class"
    assert bindings[0].target is Guard


def test_several_entries_for_a_multi_provider_token_accumulate_instead_of_colliding() -> None:
    class FirstGuard:
        pass

    class SecondGuard:
        pass

    compiled = CompiledModuleDef(
        key=_OwnerModule,
        module=_OwnerModule,
        metadata=ModuleMetadata(
            providers=(
                {"provide": APP_GUARD, "use_class": FirstGuard},
                {"provide": APP_GUARD, "use_class": SecondGuard},
            )
        ),
    )

    bindings = validate_module_compiled(compiled)

    # Each declaration keeps the resolver it was written with under a token of its own,
    # and the token the author wrote joins them, because the container holds one binding
    # per module and token.
    entries = [binding for binding in bindings if binding.token is not APP_GUARD]
    assert [binding.target for binding in entries] == [FirstGuard, SecondGuard]
    assert {binding.resolver_kind for binding in entries} == {"class"}

    joined = _joining_binding(bindings)
    assert joined.scope is ProviderScope.TRANSIENT
    _factory, inject = _joined_factory(joined)
    assert inject == tuple(binding.token for binding in entries)


def test_the_joining_binding_returns_its_components_in_declaration_order() -> None:
    compiled = CompiledModuleDef(
        key=_OwnerModule,
        module=_OwnerModule,
        metadata=ModuleMetadata(
            providers=(
                {"provide": APP_GUARD, "use_value": "first"},
                {"provide": APP_GUARD, "use_value": ["second", "third"]},
                {"provide": APP_GUARD, "use_value": "fourth"},
            )
        ),
    )

    factory, _inject = _joined_factory(_joining_binding(validate_module_compiled(compiled)))

    # A list entry contributes its own entries in place, so the two spellings mix and the
    # slot reads in the order the module was written.
    assert factory("first", ["second", "third"], "fourth") == [
        "first",
        "second",
        "third",
        "fourth",
    ]


def test_every_multi_provider_token_accumulates() -> None:
    for token in MULTI_PROVIDER_TOKENS:
        compiled = CompiledModuleDef(
            key=_OwnerModule,
            module=_OwnerModule,
            metadata=ModuleMetadata(
                providers=(
                    {"provide": token, "use_value": "first"},
                    {"provide": token, "use_value": "second"},
                )
            ),
        )

        bindings = validate_module_compiled(compiled)

        joined = [binding for binding in bindings if binding.token is token]
        assert len(joined) == 1, token
        assert len(bindings) == 3, token


def test_an_ordinary_token_declared_beside_an_accumulating_one_is_still_refused() -> None:
    compiled = CompiledModuleDef(
        key=_OwnerModule,
        module=_OwnerModule,
        metadata=ModuleMetadata(
            providers=(
                {"provide": APP_GUARD, "use_value": "first"},
                {"provide": APP_GUARD, "use_value": "second"},
                {"provide": "db", "use_value": 1},
                {"provide": "db", "use_value": 2},
            )
        ),
    )

    with pytest.raises(InvalidModuleError, match="duplicate entries in providers"):
        validate_module_compiled(compiled)


def _joined_factory(binding: Binding) -> tuple[Callable[..., list[object]], tuple[object, ...]]:
    """Return the factory a joining binding calls and the tokens it is called with."""

    return cast(tuple[Callable[..., list[object]], tuple[object, ...]], binding.target)


def _joining_binding(bindings: tuple[Binding, ...]) -> Binding:
    """Return the one binding registered under the token the module author wrote."""

    joined = [binding for binding in bindings if binding.token is APP_GUARD]
    assert len(joined) == 1
    assert joined[0].resolver_kind == "factory"
    return joined[0]


class _OwnerModule:
    pass
