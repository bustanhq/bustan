"""Compilation and validation of module definitions."""

from __future__ import annotations

from dataclasses import dataclass

from ..errors import (
    InvalidModuleError,
    InvalidProviderError,
)
from ..ioc.registry import Binding, normalize_provider, token_identity
from ..utils import _display_name, _qualname
from .dynamic import DynamicModule, ModuleInstanceKey, ModuleKey
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
                f"{_qualname(module_input.module)} is not a valid base module for dynamic "
                "registration"
            )

        merged = ModuleMetadata(
            imports=tuple(base_metadata.imports) + tuple(module_input.imports),
            controllers=tuple(base_metadata.controllers) + tuple(module_input.controllers),
            providers=tuple(base_metadata.providers) + tuple(module_input.providers),
            exports=tuple(
                dict.fromkeys(tuple(base_metadata.exports) + tuple(module_input.exports))
            ),
            is_global=base_metadata.is_global or module_input.is_global,
        )
        return CompiledModuleDef(
            key=ModuleInstanceKey(module_input.module, instance_id),
            module=module_input.module,
            metadata=merged,
        )

    base_metadata = get_module_metadata(module_input)
    if base_metadata is None:
        raise InvalidModuleError(f"{_qualname(module_input)} is not a decorated module")

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

    bindings: list[Binding] = []
    # Keyed the way the container will key them, so a token that collides here is a token
    # that would silently share one binding there.
    seen_tokens: dict[object, object] = {}

    for provider_entry in metadata.providers:
        binding = normalize_provider(provider_entry, owner)
        _reject_colliding_token(owner, seen_tokens, binding.token)
        seen_tokens[binding.token] = binding.token
        bindings.append(binding)

    return tuple(bindings)


def _reject_colliding_token(
    owner: ModuleKey, seen_tokens: dict[object, object], token: object
) -> None:
    """Reject a second provider whose token cannot be told apart from an earlier one."""

    if token not in seen_tokens:
        return

    first_token = seen_tokens[token]
    if token_identity(first_token) == token_identity(token):
        raise InvalidModuleError(
            f"{_display_name(owner)} declares duplicate entries in providers: {token!r}"
        )

    raise InvalidProviderError(
        f"Invalid provider in {_display_name(owner)}: {token!r} and {first_token!r} are equal "
        "but are not the same token, so one would silently take the other's binding; declare "
        "one of them under a distinct token"
    )


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
