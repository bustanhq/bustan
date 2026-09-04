"""Registry for dependency injection bindings and visibility rules."""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, cast

from ...common.constants import BUSTAN_PROVIDER_ATTR
from ...common.types import ProviderScope
from ..errors import InvalidProviderError
from ..module.dynamic import ModuleKey
from ..utils import _qualname
from .scopes import is_wider_scope


@dataclass(frozen=True, slots=True)
class Binding:
    """Normalized dependency injection binding."""

    token: object
    declaring_module: ModuleKey
    resolver_kind: str  # class | factory | value | existing
    target: object
    scope: ProviderScope


def normalize_provider(defn: object | dict[str, Any], declaring_module: ModuleKey) -> Binding:
    """Transform various provider definition formats into a canonical Binding."""

    if inspect.isclass(defn):
        meta: dict[str, object] = getattr(defn, BUSTAN_PROVIDER_ATTR, {})
        return Binding(
            token=meta.get("token", defn),
            declaring_module=declaring_module,
            resolver_kind="class",
            target=meta.get("use_class", defn),
            scope=ProviderScope(meta.get("scope", ProviderScope.SINGLETON)),
        )

    if isinstance(defn, dict):
        defn = cast(dict[str, Any], defn)
        token = defn.get("provide")
        if token is None:
            raise TypeError("Provider dict must provide a 'provide' key")

        scope = ProviderScope(defn.get("scope", ProviderScope.SINGLETON))

        if "use_class" in defn:
            return Binding(
                token=token,
                declaring_module=declaring_module,
                resolver_kind="class",
                target=defn["use_class"],
                scope=_use_class_scope(defn, token=token, target=defn["use_class"]),
            )
        if "use_factory" in defn:
            inject = tuple(defn.get("inject", ()))
            return Binding(
                token=token,
                declaring_module=declaring_module,
                resolver_kind="factory",
                target=(defn["use_factory"], inject),
                scope=scope,
            )
        if "use_value" in defn:
            return Binding(
                token=token,
                declaring_module=declaring_module,
                resolver_kind="value",
                target=defn["use_value"],
                scope=ProviderScope.SINGLETON,
            )
        if "use_existing" in defn:
            return Binding(
                token=token,
                declaring_module=declaring_module,
                resolver_kind="existing",
                target=defn["use_existing"],
                scope=ProviderScope.TRANSIENT,
            )

        raise TypeError(
            "Provider dict must have one of: use_class, use_factory, use_value, use_existing"
        )

    raise TypeError(f"Invalid provider definition: {defn!r}")


def _use_class_scope(defn: dict[str, Any], *, token: object, target: object) -> ProviderScope:
    """Return the scope a ``use_class`` binding registers its target under.

    A class carries the lifetime its author declared on it, and binding it under
    another token does not change what its instances are safe to hold. The dict
    may narrow that lifetime but never widen it: widening would cache one
    caller's state on a longer-lived instance, which is exactly what the
    declaration exists to prevent.
    """

    declared = (
        getattr(target, BUSTAN_PROVIDER_ATTR, {}).get("scope") if inspect.isclass(target) else None
    )
    class_scope = ProviderScope(declared) if declared is not None else None

    if "scope" not in defn:
        return class_scope if class_scope is not None else ProviderScope.SINGLETON

    dict_scope = ProviderScope(defn["scope"])
    if class_scope is not None and is_wider_scope(dict_scope, class_scope):
        raise InvalidProviderError(
            f"Provider for {_qualname(token)} binds {_qualname(target)} as "
            f"{dict_scope.value}-scoped, but the class declares {class_scope.value} scope. "
            "A binding may narrow a declared scope, never widen it, because a wider scope "
            "shares one caller's state with every later caller"
        )
    return dict_scope


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
