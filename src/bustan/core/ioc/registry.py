"""Registry for dependency injection bindings and visibility rules."""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, cast

from ...common.constants import BUSTAN_PROVIDER_ATTR
from ...common.decorators.injectable import get_provider_metadata
from ...common.types import ProviderScope
from ..errors import InvalidProviderError
from ..module.dynamic import ModuleKey
from ..utils import _display_name

DURABLE_CONTEXT_KEY_HOOK = "get_durable_context_key"

# Order is the order the keys are reported in, so it is also the order an author reads.
_USE_KEYS = ("use_class", "use_factory", "use_value", "use_existing")

# Only a constructed provider has a lifetime of its own to name. A value is one object
# and an alias borrows the lifetime of the token it points at, so a scope written beside
# either one cannot be honoured and is refused rather than dropped.
_SCOPED_USE_KEYS = frozenset({"use_class", "use_factory"})

_ALLOWED_KEYS = frozenset({"provide", "scope", "inject", *_USE_KEYS})


@dataclass(frozen=True, slots=True)
class Binding:
    """Normalized dependency injection binding."""

    token: object
    declaring_module: ModuleKey
    resolver_kind: str  # class | factory | value | existing
    target: object
    scope: ProviderScope


def token_identity(token: object) -> tuple[type[object], object]:
    """Return a token's type-aware identity.

    Python maps equal keys onto one dict entry, so a string enum member and the bare
    string it equals collide. Pairing a token with its type keeps the two apart wherever
    the framework needs to tell one declaration from another.
    """

    return (type(token), token)


def normalize_provider(defn: object | dict[str, Any], declaring_module: ModuleKey) -> Binding:
    """Transform a provider definition into a canonical binding, or refuse it.

    A class binds under its own identity. Metadata written by ``@Injectable`` describes
    the class it was written on and never its subclasses, so an undecorated subclass
    binds as itself with the default singleton lifetime instead of as its parent.

    Every malformed definition is refused as an ``InvalidProviderError`` naming the
    declaring module and the key at fault, because the author's next action is to edit
    that module and a builtin exception tells them neither.
    """

    if inspect.isclass(defn):
        return _normalize_class_provider(defn, declaring_module)

    if isinstance(defn, dict):
        return _normalize_dict_provider(cast(dict[str, Any], defn), declaring_module)

    raise _refused(declaring_module, f"{defn!r} is not a class or a provider definition dict")


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


def _normalize_dict_provider(defn: dict[str, Any], declaring_module: ModuleKey) -> Binding:
    """Validate a provider definition dict key by key before binding it."""

    unknown_keys = sorted(str(key) for key in defn if key not in _ALLOWED_KEYS)
    if unknown_keys:
        raise _refused(declaring_module, f"unknown provider keys: {', '.join(unknown_keys)}")

    if "provide" not in defn:
        raise _refused(declaring_module, "the definition has no 'provide' key")

    token = defn["provide"]
    try:
        hash(token)
    except TypeError as exc:
        raise _refused(
            declaring_module, f"the 'provide' token {token!r} cannot be used as a key"
        ) from exc

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

    scope = _resolve_declared_scope(defn, token, use_key, declaring_module)
    return _bind_dict_provider(defn, token, use_key, scope, declaring_module)


def _resolve_declared_scope(
    defn: dict[str, Any], token: object, use_key: str, declaring_module: ModuleKey
) -> ProviderScope:
    """Resolve the lifetime a definition asks for, refusing one it cannot honour."""

    if "scope" not in defn:
        return ProviderScope.TRANSIENT if use_key == "use_existing" else ProviderScope.SINGLETON

    if use_key not in _SCOPED_USE_KEYS:
        raise _refused(
            declaring_module,
            f"{token!r} declares 'scope' beside '{use_key}', which cannot honour a lifetime "
            "of its own",
        )

    declared_scope = defn["scope"]
    try:
        return ProviderScope(declared_scope)
    except (TypeError, ValueError) as exc:
        raise _refused(
            declaring_module, f"{token!r} declares an unsupported 'scope': {declared_scope!r}"
        ) from exc


def _bind_dict_provider(
    defn: dict[str, Any],
    token: object,
    use_key: str,
    scope: ProviderScope,
    declaring_module: ModuleKey,
) -> Binding:
    """Build the binding for the single ``use_*`` key the definition declared."""

    if use_key == "use_class":
        target = defn["use_class"]
        if not inspect.isclass(target):
            raise _refused(
                declaring_module,
                f"{token!r} declares a 'use_class' that is not a class: {target!r}",
            )
        _refuse_unusable_durable_key_hook(target, scope, declaring_module)
        return Binding(token, declaring_module, "class", target, scope)

    if use_key == "use_factory":
        factory = defn["use_factory"]
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
        return Binding(
            token,
            declaring_module,
            "factory",
            (factory, _coerce_inject(defn.get("inject", ()), token, declaring_module)),
            scope,
        )

    if use_key == "use_value":
        return Binding(token, declaring_module, "value", defn["use_value"], scope)

    return Binding(token, declaring_module, "existing", defn["use_existing"], scope)


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
    # A hook written as a plain method needs the instance the key is meant to select,
    # so the definition can never resolve; refuse it here rather than once per request.
    if hook is not None and not isinstance(hook, (classmethod, staticmethod)):
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


class Registry:
    """Manages the mapping of provider tokens to their resolving bindings."""

    def __init__(self) -> None:
        self.bindings: dict[tuple[ModuleKey, object], Binding] = {}
        self.module_visibility: dict[ModuleKey, dict[object, ModuleKey]] = {}
        self.controller_modules: dict[type[object], ModuleKey] = {}

    def register_binding(self, key: tuple[ModuleKey, object], binding: Binding) -> None:
        self.bindings[key] = binding

    def set_visibility(self, module_key: ModuleKey, visibility: dict[object, ModuleKey]) -> None:
        self.module_visibility[module_key] = visibility

    def register_controller(self, controller_cls: type[object], module_key: ModuleKey) -> None:
        self.controller_modules[controller_cls] = module_key

    def get_binding(self, key: tuple[ModuleKey, object]) -> Binding | None:
        return self.bindings.get(key)
