"""Registry for dependency injection bindings and visibility rules."""

from __future__ import annotations

import inspect
from collections.abc import Iterable, Iterator, Mapping, MutableMapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal, cast

from ...common.constants import BUSTAN_PROVIDER_ATTR
from ...common.decorators.injectable import get_provider_metadata

# Re-exported: the module graph, the compiler, the scope keys, the override ledger and
# the test builder all name the token identity rule through this module.
from ...common.tokens import TokenKey, token_identity
from ...common.types import (
    ClassProvider,
    ExistingProvider,
    FactoryProvider,
    ProviderDefinition,
    ProviderScope,
    ValueProvider,
)
from ..errors import InvalidProviderError
from ..module.dynamic import ModuleKey
from ..utils import _display_name

DURABLE_CONTEXT_KEY_HOOK = "get_durable_context_key"

# Which resolver a binding was built for. Every reader of a binding branches on this, so
# the four values are written here rather than described, and a fifth cannot be spelled.
type ResolverKind = Literal["class", "factory", "value", "existing"]

# Each target key a provider dict could name, paired with the value type that binds what
# such a dict declared. A dict is refused rather than read, and this pairing is what the
# refusal hands its author instead. Order is the order a dict naming several is answered
# for, and the first entry answers a dict naming none.
_DICT_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("use_class", "ClassProvider"),
    ("use_factory", "FactoryProvider"),
    ("use_value", "ValueProvider"),
    ("use_existing", "ExistingProvider"),
)

# How long a context each lifetime keeps an instance for, shortest first. A binding
# may narrow the lifetime a class declares but never widen it, and this is the order
# that judges which is which. A transient sorts shortest because it keeps nothing at
# all: rebuilding a request-scoped class for every consumer shares nothing.
_LIFETIME_ORDER: dict[ProviderScope, int] = {
    ProviderScope.TRANSIENT: 0,
    ProviderScope.REQUEST: 1,
    ProviderScope.DURABLE: 2,
    ProviderScope.SINGLETON: 3,
}


@dataclass(frozen=True, slots=True)
class Binding:
    """Normalized dependency injection binding."""

    token: object
    declaring_module: ModuleKey
    resolver_kind: ResolverKind
    target: object
    scope: ProviderScope


class TokenMap[V](MutableMapping[object, V]):
    """A mapping keyed by provider token that never merges two tokens of different types.

    A plain dict keys by equality alone, so a string enum member and the bare string it
    equals become one entry and whichever was written last answers for both. Every table
    that says what a token means keys by ``token_identity`` instead, so a token means
    what its author declared and nothing else. Lookup, membership and deletion all take
    the token as written, and iteration yields those same tokens in declaration order.

    An unhashable token raises ``TypeError`` here exactly as it would from a dict,
    because a caller that probes a mapping with an arbitrary annotation relies on it.
    """

    __slots__ = ("_entries",)

    def __init__(self, entries: Mapping[object, V] | Iterable[tuple[object, V]] = ()) -> None:
        self._entries: dict[TokenKey, V] = {}
        pairs = entries.items() if isinstance(entries, Mapping) else entries
        for token, value in pairs:
            self[token] = value

    def __getitem__(self, token: object) -> V:
        return self._entries[token_identity(token)]

    def __setitem__(self, token: object, value: V) -> None:
        self._entries[token_identity(token)] = value

    def __delitem__(self, token: object) -> None:
        del self._entries[token_identity(token)]

    def __iter__(self) -> Iterator[object]:
        # The identity carries the token itself, so the declared token is what is yielded.
        return (token for _token_type, token in self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    def __eq__(self, other: object) -> bool:
        # Comparing through a dict would collapse the very tokens this mapping keeps
        # apart, so both sides are compared by token identity.
        if isinstance(other, TokenMap):
            return self._entries == other._entries
        if isinstance(other, Mapping):
            other_entries: dict[TokenKey, object] = {
                token_identity(token): value for token, value in other.items()
            }
            return self._entries == other_entries
        return NotImplemented

    def __repr__(self) -> str:
        shown = ", ".join(f"{token!r}: {value!r}" for token, value in self.items())
        return f"{type(self).__name__}({{{shown}}})"


class BindingTable(MutableMapping[tuple[ModuleKey, object], Binding]):
    """The binding table, keyed by the declaring module and the token's identity.

    Keys are read and written as the ``(module, token)`` pair they have always been.
    The token half is keyed by identity, so asking a module for a token equal to one it
    declares, but of another type, finds nothing rather than the other token's binding.
    """

    __slots__ = ("_entries",)

    def __init__(self) -> None:
        self._entries: dict[tuple[ModuleKey, TokenKey], Binding] = {}

    def __getitem__(self, key: tuple[ModuleKey, object]) -> Binding:
        module_key, token = key
        return self._entries[(module_key, token_identity(token))]

    def __setitem__(self, key: tuple[ModuleKey, object], binding: Binding) -> None:
        module_key, token = key
        self._entries[(module_key, token_identity(token))] = binding

    def __delitem__(self, key: tuple[ModuleKey, object]) -> None:
        module_key, token = key
        del self._entries[(module_key, token_identity(token))]

    def __iter__(self) -> Iterator[tuple[ModuleKey, object]]:
        return ((module_key, token) for module_key, (_token_type, token) in self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    def __repr__(self) -> str:
        shown = ", ".join(f"{key!r}: {binding!r}" for key, binding in self.items())
        return f"{type(self).__name__}({{{shown}}})"


def normalize_provider(defn: object, declaring_module: ModuleKey) -> Binding:
    """Transform a provider declaration into a canonical binding, or refuse it.

    A class binds under its own identity. Metadata written by ``@Injectable`` describes
    the class it was written on and never its subclasses, so an undecorated subclass
    binds as itself with the default singleton lifetime instead of as its parent.

    A mapping is not a provider. It was a second way of writing these same four
    declarations, so it is refused by name and the refusal carries the value type that
    binds what it declared, rather than reporting it as an unrecognised object.

    Every malformed declaration is refused as an ``InvalidProviderError`` naming the
    declaring module and the key at fault, because the author's next action is to edit
    that module and a builtin exception tells them neither.
    """

    if inspect.isclass(defn):
        return _normalize_class_provider(defn, declaring_module)

    if isinstance(defn, (ClassProvider, FactoryProvider, ValueProvider, ExistingProvider)):
        return _bind_definition(defn, declaring_module)

    if isinstance(defn, Mapping):
        raise _refuse_mapping(cast("Mapping[object, object]", defn), declaring_module)

    raise _refused(declaring_module, f"{defn!r} is not a class or a provider definition")


def declared_token_identity(entry: object) -> TokenKey | None:
    """Return the identity of the token a provider declaration binds, or ``None``.

    ``None`` means the entry binds no token that can be read: it is not a class or a
    provider definition, or the token it names cannot be a key. That is not the same as
    binding ``None``, which is a token like any other and comes back as its own identity.

    Reading a token is deliberately forgiving, because the caller uses it to match one
    declaration against another rather than to accept it. An entry this cannot read is
    left for ``normalize_provider`` to refuse by name, so a malformed provider is
    reported as the malformed provider it is rather than by silently failing to match.
    A mapping is one of those: reading the token out of it would let a declaration an
    overlay happens to replace be dropped instead of refused.
    """

    if inspect.isclass(entry):
        token: object = entry
    elif isinstance(entry, (ClassProvider, FactoryProvider, ValueProvider, ExistingProvider)):
        token = entry.provide
    else:
        return None

    try:
        identity = token_identity(token)
        hash(identity)
    except TypeError:
        return None
    return identity


def _refused(declaring_module: ModuleKey, detail: str) -> InvalidProviderError:
    """Build the rejection every malformed provider definition is reported through."""

    return InvalidProviderError(f"Invalid provider in {_display_name(declaring_module)}: {detail}")


def _normalize_class_provider(provider_cls: type[object], declaring_module: ModuleKey) -> Binding:
    """Bind a bare class under its own identity, honouring only its own metadata."""

    metadata = get_provider_metadata(provider_cls)
    if metadata is None and BUSTAN_PROVIDER_ATTR in provider_cls.__dict__:
        raise _refused(
            declaring_module,
            f"{_display_name(provider_cls)} carries a '{BUSTAN_PROVIDER_ATTR}' attribute that is "
            "not provider metadata; declare the class with @Injectable instead of writing it",
        )

    scope = metadata.scope if metadata is not None else ProviderScope.SINGLETON
    _refuse_unusable_durable_key_hook(provider_cls, scope, declaring_module)

    return Binding(
        token=provider_cls,
        declaring_module=declaring_module,
        resolver_kind="class",
        target=provider_cls,
        scope=scope,
    )


def _refuse_mapping(
    defn: Mapping[object, object], declaring_module: ModuleKey
) -> InvalidProviderError:
    """Refuse a mapping, naming the value type that binds what it was written to declare.

    A dict was the older way to write these four declarations, so the author's whole fix
    is the one arm it stands for and the refusal carries that arm rather than a pointer
    to the guide. A mapping naming no target has no arm of its own and is answered with
    the class form, which every other arm is written by analogy to.
    """

    use_key, replacement = next(
        (pair for pair in _DICT_REPLACEMENTS if pair[0] in defn), _DICT_REPLACEMENTS[0]
    )
    return _refused(
        declaring_module,
        f'a dict is no longer a provider. Replace {{"provide": X, "{use_key}": Y}} with '
        f"{replacement}(provide=X, {use_key}=Y)",
    )


def _coerce_scope(
    declared_scope: object, token: object, declaring_module: ModuleKey
) -> ProviderScope:
    """Read a named lifetime as one this container has a rule for, or refuse it."""

    try:
        return ProviderScope(declared_scope)
    except (TypeError, ValueError) as exc:
        raise _refused(
            declaring_module, f"{token!r} declares an unsupported 'scope': {declared_scope!r}"
        ) from exc


def _carried_scope(
    declared_scope: ProviderScope | None, token: object, declaring_module: ModuleKey
) -> ProviderScope | None:
    """Return the lifetime a definition carries, or ``None`` where it names none.

    The field is declared as a lifetime, so this has only the caller who reached the
    container from unchecked code left to refuse.
    """

    if declared_scope is None:
        return None
    return _coerce_scope(declared_scope, token, declaring_module)


def _bind_definition(definition: ProviderDefinition, declaring_module: ModuleKey) -> Binding:
    """Build the binding one provider definition asks for, whichever arm it is."""

    token = definition.provide
    try:
        hash(token)
    except TypeError as exc:
        raise _refused(
            declaring_module, f"the 'provide' token {token!r} cannot be used as a key"
        ) from exc

    if isinstance(definition, ClassProvider):
        return _bind_class_definition(definition, token, declaring_module)
    if isinstance(definition, FactoryProvider):
        return _bind_factory_definition(definition, token, declaring_module)

    # Neither a value nor an alias carries a lifetime to name, so both are bound under
    # the one they always had: a value is the single object it was written as, and an
    # alias keeps nothing of its own and borrows the lifetime of the token it points at.
    if isinstance(definition, ValueProvider):
        return Binding(
            token, declaring_module, "value", definition.use_value, ProviderScope.SINGLETON
        )
    return Binding(
        token, declaring_module, "existing", definition.use_existing, ProviderScope.TRANSIENT
    )


def _bind_class_definition(
    definition: ClassProvider, token: object, declaring_module: ModuleKey
) -> Binding:
    """Bind a token to the class it names, under the lifetime the two of them settle."""

    target = definition.use_class
    if not inspect.isclass(target):
        raise _refused(
            declaring_module,
            f"{token!r} declares a 'use_class' that is not a class: {target!r}",
        )

    declared_scope = _carried_scope(definition.scope, token, declaring_module)
    scope = _use_class_scope(declared_scope, token, target, declaring_module)
    _refuse_unusable_durable_key_hook(target, scope, declaring_module)
    return Binding(token, declaring_module, "class", target, scope)


def _bind_factory_definition(
    definition: FactoryProvider, token: object, declaring_module: ModuleKey
) -> Binding:
    """Bind a token to the callable that builds it, with the tokens it is called with."""

    declared_scope = _carried_scope(definition.scope, token, declaring_module)
    scope = declared_scope if declared_scope is not None else ProviderScope.SINGLETON
    factory = definition.use_factory
    if not callable(factory):
        raise _refused(
            declaring_module,
            f"{token!r} declares a 'use_factory' that is not callable: {factory!r}",
        )
    if scope is ProviderScope.DURABLE:
        raise _refused(
            declaring_module,
            f"{token!r} asks for a durable 'use_factory'; a durable lifetime is partitioned "
            f"by a '{DURABLE_CONTEXT_KEY_HOOK}' hook, which only a class can carry",
        )
    inject = _coerce_inject(definition.inject, token, declaring_module)
    return Binding(token, declaring_module, "factory", (factory, inject), scope)


def _use_class_scope(
    declared_scope: ProviderScope | None,
    token: object,
    target: type[object],
    declaring_module: ModuleKey,
) -> ProviderScope:
    """Return the lifetime a ``use_class`` definition registers its target under.

    A class carries the lifetime its author declared on it, and binding it under
    another token does not change what its instances are safe to hold. A definition
    that names no lifetime therefore takes the class's own. One that names a lifetime
    may narrow it but never widen it: widening keeps one caller's state on an instance
    that outlives them, which is what the class's declaration exists to prevent.
    """

    metadata = get_provider_metadata(target)
    class_scope = metadata.scope if metadata is not None else None

    if declared_scope is None:
        return class_scope if class_scope is not None else ProviderScope.SINGLETON

    if class_scope is not None and _LIFETIME_ORDER[declared_scope] > _LIFETIME_ORDER[class_scope]:
        raise _refused(
            declaring_module,
            f"{token!r} binds {_display_name(target)} as {declared_scope.value}-scoped, but the "
            f"class declares {class_scope.value} scope. A binding may narrow a declared scope, "
            "never widen it, because a wider scope shares one caller's state with every later "
            "caller",
        )
    return declared_scope


def _coerce_inject(
    inject: object, token: object, declaring_module: ModuleKey
) -> tuple[object, ...]:
    """Turn a factory's declared dependencies into a tuple of tokens."""

    if isinstance(inject, (str, bytes)):
        raise _refused(
            declaring_module,
            f"{token!r} declares 'inject' as {inject!r}; a single token must still be written "
            "inside a sequence, or it is read one character at a time",
        )

    try:
        return tuple(cast(Any, inject))
    except TypeError as exc:
        raise _refused(
            declaring_module,
            f"{token!r} declares an 'inject' that is not a sequence of tokens: {inject!r}",
        ) from exc


def _refuse_unusable_durable_key_hook(
    target: type[object], scope: ProviderScope, declaring_module: ModuleKey
) -> None:
    """Refuse a durable class whose context key hook can never be called."""

    if scope is not ProviderScope.DURABLE:
        return

    hook = _declared_durable_key_hook(target)
    # A durable lifetime is a cache partitioned by a key the class derives, so a class
    # that declares no hook at all has no partition and can never resolve. There is no
    # input that makes it work, so it is refused while the graph is built rather than
    # on whichever request first happens to touch it.
    if hook is None:
        raise _refused(
            declaring_module,
            f"{_display_name(target)} asks for a durable lifetime but declares no "
            f"'{DURABLE_CONTEXT_KEY_HOOK}'; a durable instance is cached per context key, so "
            "the class must carry a classmethod or staticmethod that derives one from the "
            "request",
        )

    # A hook written as a plain method needs the instance the key is meant to select,
    # so the definition can never resolve; refuse it here rather than once per request.
    if not isinstance(hook, (classmethod, staticmethod)):
        raise _refused(
            declaring_module,
            f"{_display_name(target)} declares '{DURABLE_CONTEXT_KEY_HOOK}' as an instance "
            "method; a durable context key is derived before any instance exists, so the hook "
            "must be a classmethod or a staticmethod",
        )


def _declared_durable_key_hook(target: type[object]) -> object | None:
    """Return the durable context key hook declared anywhere on a class's ancestry."""

    for ancestor in target.__mro__:
        hook = ancestor.__dict__.get(DURABLE_CONTEXT_KEY_HOOK)
        if hook is not None:
            return hook
    return None


class VisibilityView(Mapping[ModuleKey, Mapping[object, ModuleKey]]):
    """A live read-only window onto what each module can see.

    Both levels refuse a write: the outer mapping of modules and the token map each
    module holds. Reading is a window rather than a copy, so what a caller sees is the
    registry as it stands, and a write to it is refused where it is written. A copy
    would take that second half away - the write would succeed and then be discarded,
    which is harder to notice than a refusal and leaves the caller believing the
    registry changed.
    """

    __slots__ = ("_visibility",)

    def __init__(self, visibility: Mapping[ModuleKey, TokenMap[ModuleKey]]) -> None:
        self._visibility = visibility

    def __getitem__(self, module_key: ModuleKey) -> Mapping[object, ModuleKey]:
        return MappingProxyType(self._visibility[module_key])

    def __iter__(self) -> Iterator[ModuleKey]:
        return iter(self._visibility)

    def __len__(self) -> int:
        return len(self._visibility)

    def __repr__(self) -> str:
        shown = ", ".join(f"{module_key!r}: {visible!r}" for module_key, visible in self.items())
        return f"{type(self).__name__}({{{shown}}})"


class Registry:
    """Manages the mapping of provider tokens to their resolving bindings.

    The three tables are held privately and are written only by the register methods
    below. Nothing re-checks a table after the graph is validated, so a table a caller
    could assign into is one the container would go on trusting while it described an
    application that no longer exists. Reading is served by the three views, which are
    live windows rather than copies and refuse a write where it is made.
    """

    def __init__(self) -> None:
        self._bindings: BindingTable = BindingTable()
        self._module_visibility: dict[ModuleKey, TokenMap[ModuleKey]] = {}
        self._controller_modules: dict[type[object], ModuleKey] = {}

    def register_binding(self, key: tuple[ModuleKey, object], binding: Binding) -> None:
        """Record the binding a module declares for a token."""

        self._bindings[key] = binding

    def set_visibility(self, module_key: ModuleKey, visibility: Mapping[object, ModuleKey]) -> None:
        """Record what one module can see, keyed so equal tokens of two types stay apart."""

        self._module_visibility[module_key] = TokenMap(visibility)

    def register_controller(self, controller_cls: type[object], module_key: ModuleKey) -> None:
        """Record the module a controller was declared in."""

        self._controller_modules[controller_cls] = module_key

    def get_binding(self, key: tuple[ModuleKey, object]) -> Binding | None:
        """Return the binding a module declares for a token, or ``None`` for no binding."""

        return self._bindings.get(key)

    @property
    def binding_view(self) -> Mapping[tuple[ModuleKey, object], Binding]:
        """A live read-only window onto every binding, keyed by module and token."""

        return MappingProxyType(self._bindings)

    @property
    def visibility_view(self) -> VisibilityView:
        """A live read-only window onto what each module can see."""

        return VisibilityView(self._module_visibility)

    @property
    def controller_module_view(self) -> Mapping[type[object], ModuleKey]:
        """A live read-only window onto which module declares each controller."""

        return MappingProxyType(self._controller_modules)
