"""Compilation and validation of module definitions."""

from __future__ import annotations

from dataclasses import dataclass, replace

from ...common.types import ProviderScope
from ..errors import (
    InvalidModuleError,
    InvalidProviderError,
)
from ..ioc.registry import Binding, TokenKey, normalize_provider, token_identity
from ..ioc.tokens import APP_FILTER, APP_GUARD, APP_INTERCEPTOR, APP_PIPE, InjectionToken
from ..utils import _display_name, _qualname
from .dynamic import DynamicModule, ModuleInstanceKey, ModuleKey
from .metadata import ModuleMetadata, get_module_metadata

# The tokens a module may declare more than once. Every other token names one binding, so
# a second provider for it means one of the two silently wins and the declaration is a
# mistake. These four name a pipeline slot that runs everything declared for it, so a
# second provider adds a component to the slot rather than replacing the first. This is
# the only statement of which tokens behave that way.
MULTI_PROVIDER_TOKENS: tuple[InjectionToken[object], ...] = (
    APP_GUARD,
    APP_PIPE,
    APP_INTERCEPTOR,
    APP_FILTER,
)

_MULTI_PROVIDER_TOKENS_BY_IDENTITY: dict[TokenKey, InjectionToken[object]] = {
    token_identity(token): token for token in MULTI_PROVIDER_TOKENS
}


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
    """Validate a compiled module definition and return its normalized bindings.

    One binding comes back per token the module declares, not per entry it wrote: a token
    several providers may accumulate under is returned as one binding joining them all,
    because the container holds a single binding for each module and token.
    """

    owner = compiled.key
    metadata = compiled.metadata

    _validate_unique_entries(owner, "imports", metadata.imports)
    _validate_unique_entries(owner, "controllers", metadata.controllers)
    _validate_unique_entries(owner, "exports", metadata.exports)

    return _accumulate_multi_provider_tokens(owner, _normalized_bindings(owner, metadata.providers))


def _normalized_bindings(
    owner: ModuleKey, provider_entries: tuple[object, ...]
) -> tuple[Binding, ...]:
    """Bind every provider entry a module declares, refusing one that collides."""

    bindings: list[Binding] = []
    # Keyed the way the container will key them, so a token that collides here is a token
    # that would silently share one binding there.
    seen_tokens: dict[object, object] = {}

    for provider_entry in provider_entries:
        binding = normalize_provider(provider_entry, owner)
        # A multi-provider token accumulates instead of colliding: a second declaration
        # for it adds a component to a slot that runs all of them, so there is no losing
        # binding to warn about.
        if not _accumulates(binding.token):
            _reject_colliding_token(owner, seen_tokens, binding.token)
            seen_tokens[binding.token] = binding.token
        bindings.append(binding)

    return tuple(bindings)


def _accumulates(token: object) -> bool:
    """Return whether several providers for this token add up rather than collide."""

    return token_identity(token) in _MULTI_PROVIDER_TOKENS_BY_IDENTITY


def _accumulate_multi_provider_tokens(
    owner: ModuleKey, bindings: tuple[Binding, ...]
) -> tuple[Binding, ...]:
    """Fold repeated declarations of one multi-provider token into a single binding.

    The container holds one binding per module and token, so a module that declares a
    multi-provider token more than once is rewritten here into a shape it can hold: each
    declaration keeps the resolver and the lifetime it was written with under a token of
    its own, and the token the author wrote is bound to all of them at once. A module
    that declares such a token once is left exactly as it was written.
    """

    groups: dict[TokenKey, list[Binding]] = {}
    for binding in bindings:
        if _accumulates(binding.token):
            groups.setdefault(token_identity(binding.token), []).append(binding)

    if not any(len(group) > 1 for group in groups.values()):
        return bindings

    accumulated: list[Binding] = []
    folded: set[TokenKey] = set()
    for binding in bindings:
        identity = token_identity(binding.token)
        group = groups.get(identity)
        if group is None or len(group) == 1:
            accumulated.append(binding)
            continue
        # The whole group is emitted where its first declaration stood, so the module's
        # bindings stay in the order the module was written.
        if identity in folded:
            continue
        folded.add(identity)
        accumulated.extend(
            _folded_group(owner, _MULTI_PROVIDER_TOKENS_BY_IDENTITY[identity], group)
        )

    return tuple(accumulated)


def _folded_group(
    owner: ModuleKey, token: InjectionToken[object], group: list[Binding]
) -> tuple[Binding, ...]:
    """Rebind each declaration under a private token and join them under the real one.

    The joining binding is transient, so it caches nothing of its own and the lifetime it
    hands whoever holds it is still the shortest of the declarations it joins. A
    request-scoped component declared beside a singleton one is therefore still judged,
    and still built, as request-scoped.
    """

    entry_tokens: list[object] = []
    entries: list[Binding] = []
    for position, binding in enumerate(group):
        entry_token: InjectionToken[object] = InjectionToken(
            f"{token.name}[{position}] in {_display_name(owner)}"
        )
        entry_tokens.append(entry_token)
        entries.append(replace(binding, token=entry_token))

    joined = Binding(
        token=token,
        declaring_module=owner,
        resolver_kind="factory",
        target=(_in_declaration_order, tuple(entry_tokens)),
        scope=ProviderScope.TRANSIENT,
    )
    return (*entries, joined)


def _in_declaration_order(*components: object) -> list[object]:
    """Return every component declared under one multi-provider token, in order.

    A declaration naming a list of components contributes its entries in place rather
    than as one nested component, so a module may spell some of its components out one
    at a time and some as a list, and the slot still runs them in the order the module
    reads.
    """

    ordered: list[object] = []
    for component in components:
        if isinstance(component, (list, tuple)):
            ordered.extend(component)
        else:
            ordered.append(component)
    return ordered


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
