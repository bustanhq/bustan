"""Metadata structures for the processing pipeline (guards, pipes, filters)."""

from __future__ import annotations

from dataclasses import dataclass
from types import FunctionType
from typing import TypeVar

from ..core.utils import _get_metadata, _unwrap_handler

ClassT = TypeVar("ClassT", bound=type[object])
FunctionT = TypeVar("FunctionT", bound=FunctionType)

CONTROLLER_PIPELINE_ATTR = "__bustan_controller_pipeline_metadata__"
HANDLER_PIPELINE_ATTR = "__bustan_handler_pipeline_metadata__"


@dataclass(frozen=True, slots=True)
class PipelineMetadata:
    """Merged pipeline component declarations for a controller or handler."""

    guards: tuple[object, ...] = ()
    pipes: tuple[object, ...] = ()
    interceptors: tuple[object, ...] = ()
    filters: tuple[object, ...] = ()


def set_controller_pipeline_metadata(controller_cls: ClassT, metadata: PipelineMetadata) -> ClassT:
    setattr(controller_cls, CONTROLLER_PIPELINE_ATTR, metadata)
    return controller_cls


def get_controller_pipeline_metadata(
    controller_cls: type[object], *, inherit: bool = False
) -> PipelineMetadata | None:
    metadata = _get_metadata(controller_cls, CONTROLLER_PIPELINE_ATTR, inherit=inherit)
    return metadata if isinstance(metadata, PipelineMetadata) else None


def set_handler_pipeline_metadata(handler: FunctionT, metadata: PipelineMetadata) -> FunctionT:
    setattr(handler, HANDLER_PIPELINE_ATTR, metadata)
    return handler


def get_handler_pipeline_metadata(handler: object) -> PipelineMetadata | None:
    unwrapped_handler = _unwrap_handler(handler)
    if unwrapped_handler is None:
        return None

    metadata = getattr(unwrapped_handler, HANDLER_PIPELINE_ATTR, None)
    return metadata if isinstance(metadata, PipelineMetadata) else None


def extend_controller_pipeline_metadata(
    controller_cls: ClassT,
    *,
    guards: tuple[object, ...] = (),
    pipes: tuple[object, ...] = (),
    interceptors: tuple[object, ...] = (),
    filters: tuple[object, ...] = (),
) -> ClassT:
    existing_metadata = get_controller_pipeline_metadata(controller_cls) or PipelineMetadata()
    merged_metadata = merge_pipeline_metadata(
        existing_metadata,
        PipelineMetadata(
            guards=guards,
            pipes=pipes,
            interceptors=interceptors,
            filters=filters,
        ),
    )
    return set_controller_pipeline_metadata(controller_cls, merged_metadata)


def extend_handler_pipeline_metadata(
    handler: FunctionT,
    *,
    guards: tuple[object, ...] = (),
    pipes: tuple[object, ...] = (),
    interceptors: tuple[object, ...] = (),
    filters: tuple[object, ...] = (),
) -> FunctionT:
    existing_metadata = get_handler_pipeline_metadata(handler) or PipelineMetadata()
    merged_metadata = merge_pipeline_metadata(
        existing_metadata,
        PipelineMetadata(
            guards=guards,
            pipes=pipes,
            interceptors=interceptors,
            filters=filters,
        ),
    )
    return set_handler_pipeline_metadata(handler, merged_metadata)


def merge_pipeline_metadata(*metadata_items: PipelineMetadata) -> PipelineMetadata:
    """Merge pipeline metadata while preserving declaration order."""

    guards: list[object] = []
    pipes: list[object] = []
    interceptors: list[object] = []
    filters: list[object] = []

    for metadata in metadata_items:
        guards.extend(metadata.guards)
        pipes.extend(metadata.pipes)
        interceptors.extend(metadata.interceptors)
        filters.extend(metadata.filters)

    return PipelineMetadata(
        guards=tuple(guards),
        pipes=tuple(pipes),
        interceptors=tuple(interceptors),
        filters=tuple(filters),
    )
