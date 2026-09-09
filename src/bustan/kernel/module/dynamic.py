"""Dynamic module registrations and unique instance keys."""

from __future__ import annotations

from dataclasses import dataclass

from ...common.types import Provider


@dataclass(frozen=True, slots=True)
class ModuleInstanceKey:
    """Unique identity for one dynamic registration of a module."""

    module: type[object]
    instance_id: str


ModuleKey = type[object] | ModuleInstanceKey

# Every distinct dynamic registration, keyed by its own value. It grows only while
# modules are being declared, which happens at import and at bootstrap and never in
# response to a request.
_REGISTRATIONS: dict[object, DynamicModule] = {}


@dataclass(frozen=True, slots=True)
class DynamicModule:
    """Metadata overlay that compiles into a unique module instance.

    Two registrations that declare the same thing *are* the same registration: calling
    ``for_root(options)`` twice with the same options describes one module, not two,
    and building both would give the application two copies of every provider inside
    it and two sets of their singletons. Constructing one therefore returns the
    registration that already describes those values whenever there is one, so identity
    follows the declaration rather than the order the objects were created in.

    What the overlay declares wins over the base module. A provider here replaces the
    base module's provider for the same token, which is what lets a base module declare
    a default and a registration configure it away; a global pipeline token is the one
    exception, because a second declaration of one of those adds a component to a slot
    that runs them all. An import or a controller the base module already names is one
    entry rather than two, so naming it again here adds nothing and is not an error.
    """

    module: type[object]
    providers: tuple[Provider, ...] = ()
    imports: tuple[type[object] | DynamicModule, ...] = ()
    controllers: tuple[type[object], ...] = ()
    exports: tuple[object, ...] = ()
    is_global: bool = False

    def __new__(
        cls,
        module: type[object],
        providers: tuple[Provider, ...] = (),
        imports: tuple[type[object] | DynamicModule, ...] = (),
        controllers: tuple[type[object], ...] = (),
        exports: tuple[object, ...] = (),
        is_global: bool = False,
    ) -> DynamicModule:
        identity = _identity_of((cls, module, providers, imports, controllers, exports, is_global))
        registered = _REGISTRATIONS.get(identity)
        if registered is not None:
            return registered
        # The fields are exactly these arguments, so the instance the generated
        # __init__ is about to fill in is already the one this identity describes.
        created = object.__new__(cls)
        _REGISTRATIONS[identity] = created
        return created


def _identity_of(value: object) -> object:
    """Return a hashable stand-in for a declaration, so equal declarations match.

    A declaration is a sequence of entries, so it is read structurally down to its
    leaves. A leaf is paired with its own type, because a string enum member and the
    bare string it equals are two different declarations. A leaf nothing can hash - a
    provider holding an arbitrary object as its ``use_value`` - stands for itself, which
    is the strictest answer available and so never merges two declarations that are not
    the same one.
    """

    if isinstance(value, (list, tuple)):
        return ("sequence", tuple(_identity_of(item) for item in value))
    try:
        hash(value)
    except TypeError:
        return ("unhashable", id(value))
    return (type(value), value)
