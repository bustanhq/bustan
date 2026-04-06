"""Dynamic module registrations and unique instance keys."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ModuleInstanceKey:
    """Unique identity for one dynamic registration of a module."""

    module: type[object]
    instance_id: str


ModuleKey = type[object] | ModuleInstanceKey


@dataclass(frozen=True, slots=True)
class DynamicModule:
    """Metadata overlay that compiles into a unique module instance."""

    module: type[object]
    providers: tuple[object | dict[str, Any], ...] = ()
    imports: tuple[type[object] | DynamicModule, ...] = ()
    controllers: tuple[type[object], ...] = ()
    exports: tuple[object, ...] = ()
