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

# The keys of the provider definition dict, which is the older way to write a provider
# and is read here into the value type that describes the same declaration. Order is the
# order the keys are reported in, so it is also the order an author reads.
_USE_KEYS = ("use_class", "use_factory", "use_value", "use_existing")

# Only a constructed provider has a lifetime of its own to name. A value is one object
# and an alias borrows the lifetime of the token it points at, so a scope written beside
# either one cannot be honoured and is refused rather than dropped.
_SCOPED_USE_KEYS = frozenset({"use_class", "use_factory"})

_ALLOWED_KEYS = frozenset({"provide", "scope", "inject", *_USE_KEYS})

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

    A definition dict is read into the value type describing the same declaration and
    then bound the same way, so the two ways of writing a provider cannot drift apart.

    Every malformed declaration is refused as an ``InvalidProviderError`` naming the
    declaring module and the key at fault, because the author's next action is to edit
    that module and a builtin exception tells them neither.
    """

    if inspect.isclass(defn):
        return _normalize_class_provider(defn, declaring_module)

    if isinstance(defn, (ClassProvider, FactoryProvider, ValueProvider, ExistingProvider)):
        return _bind_definition(defn, declaring_module)

    if isinstance(defn, dict):
        return _bind_definition(
            _definition_from_dict(cast("dict[str, Any]", defn), declaring_module), declaring_module
        )

    raise _refused(declaring_module, f"{defn!r} is not a class or a provider definition")


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


def _definition_from_dict(defn: dict[str, Any], declaring_module: ModuleKey) -> ProviderDefinition:
    """Read a provider definition dict into the value type describing the same provider.

    Every rule enforced here is a rule the value types make unwritable: which keys exist,
    that exactly one target is named, and that ``inject`` and ``scope`` appear only beside
    a target that can carry them. A declaration written as a value type therefore reaches
    the binder having already satisfied all of them.
    """

    unknown_keys = sorted(str(key) for key in defn if key not in _ALLOWED_KEYS)
    if unknown_keys:
        raise _refused(declaring_module, f"unknown provider keys: {', '.join(unknown_keys)}")

    if "provide" not in defn:
        raise _refused(declaring_module, "the definition has no 'provide' key")

    token = defn["provide"]
    declared = [key for key in _USE_KEYS if key in defn]
    if not declared:
        raise _refused(declaring_module, f"{token!r} declares none of {', '.join(_USE_KEYS)}")
    if len(declared) > 1:
        raise _refused(
            declaring_module, f"{token!r} declares more than one of {', '.join(declared)}"
        )

    use_key = declared[0]
    if "inject" in defn and use_key != "use_factory":
        raise _refused(
            declaring_module,
            f"{token!r} declares 'inject' beside '{use_key}', which takes no dependencies",
        )

    scope = _declared_scope(defn, token, use_key, declaring_module)
    if use_key == "use_class":
        return ClassProvider(token, defn["use_class"], scope)
    if use_key == "use_factory":
        inject = _coerce_inject(defn.get("inject", ()), token, declaring_module)
        return FactoryProvider(token, defn["use_factory"], inject, scope)
    if use_key == "use_value":
        return ValueProvider(token, defn["use_value"])
    return ExistingProvider(token, defn["use_existing"])


def _declared_scope(
    defn: dict[str, Any], token: object, use_key: str, declaring_module: ModuleKey
) -> ProviderScope | None:
    """Return the lifetime a definition dict names, refusing one it cannot honour.

    A dict with no ``scope`` key named no lifetime, which is not the same as naming the
    default: a ``use_class`` that names none takes the one its target declares. Writing
    the key is naming a lifetime, so every value written there has to be one.
    """

    if "scope" not in defn:
        return None

    if use_key not in _SCOPED_USE_KEYS:
        raise _refused(
            declaring_module,
            f"{token!r} declares 'scope' beside '{use_key}', which cannot honour a lifetime "
            "of its own",
        )
    return _coerce_scope(defn["scope"], token, declaring_module)


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
    """Manages the mapping of provider tokens to their resolving bindings."""

    def __init__(self) -> None:
        self.bindings: BindingTable = BindingTable()
        self.module_visibility: dict[ModuleKey, TokenMap[ModuleKey]] = {}
        self.controller_modules: dict[type[object], ModuleKey] = {}

    def register_binding(self, key: tuple[ModuleKey, object], binding: Binding) -> None:
        self.bindings[key] = binding

    def set_visibility(self, module_key: ModuleKey, visibility: Mapping[object, ModuleKey]) -> None:
        """Record what one module can see, keyed so equal tokens of two types stay apart."""

        self.module_visibility[module_key] = TokenMap(visibility)

    def register_controller(self, controller_cls: type[object], module_key: ModuleKey) -> None:
        self.controller_modules[controller_cls] = module_key

    def get_binding(self, key: tuple[ModuleKey, object]) -> Binding | None:
        return self.bindings.get(key)

    @property
    def binding_view(self) -> Mapping[tuple[ModuleKey, object], Binding]:
        """A live read-only window onto every binding, keyed by module and token."""

        return MappingProxyType(self.bindings)

    @property
    def visibility_view(self) -> VisibilityView:
        """A live read-only window onto what each module can see."""

        return VisibilityView(self.module_visibility)

    @property
    def controller_module_view(self) -> Mapping[type[object], ModuleKey]:
        """A live read-only window onto which module declares each controller."""

        return MappingProxyType(self.controller_modules)
