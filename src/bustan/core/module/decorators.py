"""Decorators for declaring modules."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, MappingView, Set
from dataclasses import replace
from typing import Any, TypeVar, cast

from ...core.errors import InvalidModuleError
from .dynamic import DynamicModule
from .metadata import ModuleMetadata, get_module_metadata, set_module_metadata

ClassT = TypeVar("ClassT", bound=type[object])


def Module(
    *,
    imports: Iterable[type[object] | DynamicModule] | None = None,
    controllers: Iterable[type[object]] | None = None,
    providers: Iterable[object | dict[str, Any]] | None = None,
    exports: Iterable[object] | None = None,
    is_global: bool = False,
) -> Callable[[ClassT], ClassT]:
    """Attach module metadata to a class without performing registration."""

    module_metadata = ModuleMetadata(
        imports=cast(
            tuple[type[object] | DynamicModule, ...], _coerce_tuple(imports, field_name="imports")
        ),
        controllers=cast(
            tuple[type[object], ...], _coerce_tuple(controllers, field_name="controllers")
        ),
        providers=_coerce_tuple(providers, field_name="providers"),
        exports=_coerce_tuple(exports, field_name="exports"),
        is_global=is_global,
    )

    def decorate(module_cls: ClassT) -> ClassT:
        if not isinstance(module_cls, type):
            raise InvalidModuleError("@Module can only decorate classes")
        # Two declarations on one class have no merge rule, so the second would replace
        # the first and quietly discard everything the first declared.
        if get_module_metadata(module_cls) is not None:
            raise InvalidModuleError(
                f"{module_cls.__name__} is already decorated with @Module; one class declares "
                "its imports, controllers, providers and exports exactly once"
            )
        return set_module_metadata(module_cls, module_metadata)

    return decorate


def Global() -> Callable[[ClassT], ClassT]:
    """Promote an existing module declaration to a global module."""

    def decorate(module_cls: ClassT) -> ClassT:
        if not isinstance(module_cls, type):
            raise InvalidModuleError("@Global can only decorate classes")

        metadata = get_module_metadata(module_cls)
        if metadata is None:
            raise InvalidModuleError(
                "@Global can only decorate classes already decorated with @Module"
            )

        # Replace immutable metadata so other decorators never observe partially mutated state.
        return set_module_metadata(module_cls, replace(metadata, is_global=True))

    return decorate


def _coerce_tuple(
    values: Iterable[object] | None,
    *,
    field_name: str,
) -> tuple[object, ...]:
    """Ensure that a module metadata field is a tuple of objects."""
    if values is None:
        return ()
    if isinstance(values, (str, bytes)):
        raise InvalidModuleError(f"Module {field_name} must be an iterable of objects")
    if isinstance(values, Mapping):
        raise InvalidModuleError(
            f"Module {field_name} must be an iterable of objects, and a mapping is read as its "
            "keys; a single provider definition must still be written inside a sequence"
        )
    # Declaration order decides construction and lifecycle-hook order, so a set makes
    # those orders vary between interpreter runs. A view over a mapping is exempt:
    # it is a set by protocol but iterates in the mapping's own insertion order.
    if isinstance(values, Set) and not isinstance(values, MappingView):
        raise InvalidModuleError(
            f"Module {field_name} must be an ordered iterable of objects, and "
            f"{type(values).__name__} does not preserve declaration order"
        )

    try:
        return tuple(values)
    except TypeError as exc:
        raise InvalidModuleError(f"Module {field_name} must be an iterable of objects") from exc
