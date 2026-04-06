"""Decorators for declaring modules."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any, TypeVar, cast

from ...core.errors import InvalidModuleError
from .dynamic import DynamicModule
from .metadata import ModuleMetadata, set_module_metadata

ClassT = TypeVar("ClassT", bound=type[object])


def Module(
    *,
    imports: Iterable[type[object] | DynamicModule] | None = None,
    controllers: Iterable[type[object]] | None = None,
    providers: Iterable[object | dict[str, Any]] | None = None,
    exports: Iterable[object] | None = None,
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
    )

    def decorate(module_cls: ClassT) -> ClassT:
        if not isinstance(module_cls, type):
            raise InvalidModuleError("@Module can only decorate classes")
        return set_module_metadata(module_cls, module_metadata)

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

    try:
        return tuple(values)
    except TypeError as exc:
        raise InvalidModuleError(f"Module {field_name} must be an iterable of objects") from exc
