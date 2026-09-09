"""Metadata structures for static module declarations."""

from __future__ import annotations

from dataclasses import dataclass

from ...common.constants import BUSTAN_MODULE_ATTR as MODULE_METADATA_ATTR
from ...kernel.utils import _get_metadata
from .dynamic import DynamicModule


@dataclass(frozen=True, slots=True)
class ModuleMetadata:
    """Static metadata captured from a @Module declaration.

    ``providers`` holds what the author wrote, entry by entry, before anything has judged
    it. Every other declaration surface names the provider union, but this one cannot:
    the entries reach here unvalidated, and refusing one by name, with the module it was
    declared in, is what normalization exists to do.
    """

    providers: tuple[object, ...] = ()
    imports: tuple[type[object] | DynamicModule, ...] = ()
    controllers: tuple[type[object], ...] = ()
    exports: tuple[object, ...] = ()
    is_global: bool = False


def set_module_metadata[ClassT: type[object]](
    module_cls: ClassT, metadata: ModuleMetadata
) -> ClassT:
    """Attach module metadata to a class."""
    setattr(module_cls, MODULE_METADATA_ATTR, metadata)
    return module_cls


def get_module_metadata(
    module_cls: type[object], *, inherit: bool = False
) -> ModuleMetadata | None:
    """Retrieve metadata from a module class."""
    metadata = _get_metadata(module_cls, MODULE_METADATA_ATTR, inherit=inherit)
    return metadata if isinstance(metadata, ModuleMetadata) else None
