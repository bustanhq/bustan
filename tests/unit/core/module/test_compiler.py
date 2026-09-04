"""Unit tests for compiled module validation helpers."""

from __future__ import annotations

from enum import StrEnum

import pytest

from bustan import Module
from bustan.core.errors import InvalidModuleError, InvalidProviderError
from bustan.core.module.compiler import (
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


class _OwnerModule:
    pass
