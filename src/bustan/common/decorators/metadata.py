"""Typed metadata decorators and lookup helpers."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Generic, TypeVar, cast

from ...common.constants import BUSTAN_METADATA_ATTR_PREFIX
from ...core.utils import _get_metadata

DecoratedT = TypeVar("DecoratedT", bound=object)
MetadataT = TypeVar("MetadataT")


def _metadata_attr_name(name: str) -> str:
    normalized_name = name.strip()
    if not normalized_name:
        raise ValueError("Metadata decorator names cannot be empty")
    return f"{BUSTAN_METADATA_ATTR_PREFIX}_{normalized_name}"


@dataclass(frozen=True, slots=True)
class MetadataKey(Generic[MetadataT]):
    """Stable identifier for framework-consumed metadata."""

    name: str
    attr_name: str


class MetadataDecorator(Generic[MetadataT]):
    """Typed decorator factory bound to one metadata key."""

    def __init__(self, key: MetadataKey[MetadataT]) -> None:
        self._key = key

    @property
    def key(self) -> MetadataKey[MetadataT]:
        return self._key

    def __call__(self, value: MetadataT) -> Callable[[DecoratedT], DecoratedT]:
        def decorate(target: DecoratedT) -> DecoratedT:
            setattr(target, self._key.attr_name, value)
            return target

        return decorate


def override_metadata(*values: MetadataT | None) -> MetadataT | None:
    """Return the first declared metadata value in precedence order."""

    for value in values:
        if value is not None:
            return value
    return None


def merge_metadata(*value_groups: Iterable[MetadataT] | None) -> tuple[MetadataT, ...]:
    """Merge metadata collections while preserving caller order."""

    merged: list[MetadataT] = []
    for group in value_groups:
        if group is None:
            continue
        merged.extend(group)
    return tuple(merged)


def _coerce_metadata_key(
    metadata: MetadataKey[MetadataT] | MetadataDecorator[MetadataT],
) -> MetadataKey[MetadataT]:
    if isinstance(metadata, MetadataDecorator):
        return metadata.key
    return metadata


class Reflector:
    """Read framework metadata with deterministic precedence rules."""

    @staticmethod
    def create_decorator(name: str) -> MetadataDecorator[MetadataT]:
        return MetadataDecorator(MetadataKey(name=name, attr_name=_metadata_attr_name(name)))

    def get(
        self,
        metadata: MetadataKey[MetadataT] | MetadataDecorator[MetadataT],
        target: object,
        *,
        inherit: bool = False,
    ) -> MetadataT | None:
        key = _coerce_metadata_key(metadata)
        value = _get_metadata(target, key.attr_name, inherit=inherit)
        return cast(MetadataT | None, value)

    def get_all_and_override(
        self,
        metadata: MetadataKey[MetadataT] | MetadataDecorator[MetadataT],
        targets: Sequence[object],
        *,
        inherit: bool = False,
    ) -> MetadataT | None:
        return override_metadata(*(self.get(metadata, target, inherit=inherit) for target in targets))

    def get_all_and_merge(
        self,
        metadata: MetadataKey[MetadataT] | MetadataDecorator[MetadataT],
        targets: Sequence[object],
        *,
        inherit: bool = False,
    ) -> tuple[MetadataT, ...]:
        value_groups: list[Iterable[MetadataT]] = []
        for target in targets:
            value = self.get(metadata, target, inherit=inherit)
            if value is None:
                continue
            if isinstance(value, tuple):
                value_groups.append(value)
                continue
            if isinstance(value, list):
                value_groups.append(tuple(value))
                continue
            value_groups.append((value,))
        return merge_metadata(*value_groups)
