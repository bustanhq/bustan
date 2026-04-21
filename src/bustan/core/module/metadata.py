"""Metadata structures for static module declarations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypeVar

from ...common.constants import BUSTAN_MODULE_ATTR as MODULE_METADATA_ATTR
from ...core.utils import _get_metadata
from .dynamic import DynamicModule

ClassT = TypeVar("ClassT", bound=type[object])



@dataclass(frozen=True, slots=True)
class ModuleMetadata:
    """Static metadata captured from a @Module declaration."""

    providers: tuple[object | dict[str, Any], ...] = ()
    imports: tuple[type[object] | DynamicModule, ...] = ()
    controllers: tuple[type[object], ...] = ()
    exports: tuple[object, ...] = ()
    is_global: bool = False


def set_module_metadata(module_cls: ClassT, metadata: ModuleMetadata) -> ClassT:
    """Attach module metadata to a class."""
    setattr(module_cls, MODULE_METADATA_ATTR, metadata)
    return module_cls


def get_module_metadata(
    module_cls: type[object], *, inherit: bool = False
) -> ModuleMetadata | None:
    """Retrieve metadata from a module class."""
    metadata = _get_metadata(module_cls, MODULE_METADATA_ATTR, inherit=inherit)
    return metadata if isinstance(metadata, ModuleMetadata) else None
