"""Compilation and validation of module definitions."""

from __future__ import annotations

from dataclasses import dataclass

from ..errors import (
    InvalidModuleError,
    InvalidProviderError,
)
from ..ioc.registry import Binding, normalize_provider
from ..utils import _display_name, _qualname
from .dynamic import DynamicModule, ModuleKey, ModuleInstanceKey
from .metadata import ModuleMetadata, get_module_metadata


@dataclass(frozen=True, slots=True)
class CompiledModuleDef:
    """Expansion of a module input into its final metadata and unique key."""

    key: ModuleKey
    module: type[object]
    metadata: ModuleMetadata


def expand_module_input(
    module_input: type[object] | DynamicModule, *, instance_id: str
) -> CompiledModuleDef:
    """Resolve a module input into its compiled metadata and unique identity key."""

    if isinstance(module_input, DynamicModule):
        base_metadata = get_module_metadata(module_input.module)
        if base_metadata is None:
            raise InvalidModuleError(
                f"{_qualname(module_input.module)} is not a valid base module for dynamic registration"
            )

        merged = ModuleMetadata(
            imports=tuple(base_metadata.imports) + tuple(module_input.imports),
            controllers=tuple(base_metadata.controllers) + tuple(module_input.controllers),
            providers=tuple(base_metadata.providers) + tuple(module_input.providers),
            exports=tuple(
                dict.fromkeys(tuple(base_metadata.exports) + tuple(module_input.exports))
            ),
        )
        return CompiledModuleDef(
            key=ModuleInstanceKey(module_input.module, instance_id),
            module=module_input.module,
            metadata=merged,
        )

    base_metadata = get_module_metadata(module_input)
    if base_metadata is None:
        raise InvalidModuleError(
            f"{_qualname(module_input)} is not a decorated module"
        )

    return CompiledModuleDef(
        key=module_input,
        module=module_input,
        metadata=base_metadata,
    )


def validate_module_compiled(
    compiled: CompiledModuleDef,
) -> tuple[Binding, ...]:
    """Validate a compiled module definition and return its normalized bindings."""

    owner = compiled.key
    metadata = compiled.metadata

    _validate_unique_entries(owner, "imports", metadata.imports)
    _validate_unique_entries(owner, "controllers", metadata.controllers)
    _validate_unique_entries(owner, "exports", metadata.exports)

    # Note: Structural validation (require_module, require_controller)
    # continues to be part of the compilation phase to catch errors early.

    bindings: list[Binding] = []
    seen_tokens: set[object] = set()

    for provider_entry in metadata.providers:
        try:
            binding = normalize_provider(provider_entry, owner)
        except TypeError as exc:
            raise InvalidProviderError(
                f"Invalid provider in {_display_name(owner)}: {exc}"
            ) from exc

        if binding.token in seen_tokens:
            raise InvalidModuleError(
                f"{_display_name(owner)} declares duplicate entries in providers: {binding.token!r}"
            )
        seen_tokens.add(binding.token)
        bindings.append(binding)

    return tuple(bindings)


def _validate_unique_entries(
    owner: ModuleKey,
    field_name: str,
    entries: tuple[object, ...],
) -> None:
    """Verify that a module's metadata fields do not contain duplicate identities."""
    seen_identities: set[int | object] = set()
    for entry in entries:
        ident_val = id(entry) if isinstance(entry, DynamicModule) else entry
        if ident_val in seen_identities:
            raise InvalidModuleError(
                f"{_display_name(owner)} declares duplicate entries in {field_name}: {entry!r}"
            )
        seen_identities.add(ident_val)
