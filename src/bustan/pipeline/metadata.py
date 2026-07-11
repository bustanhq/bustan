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
CONTROLLER_POLICY_ATTR = "__bustan_controller_policy_metadata__"
HANDLER_POLICY_ATTR = "__bustan_handler_policy_metadata__"


@dataclass(frozen=True, slots=True)
class PipelineMetadata:
    """Merged pipeline component declarations for a controller or handler."""

    guards: tuple[object, ...] = ()
    pipes: tuple[object, ...] = ()
    interceptors: tuple[object, ...] = ()
    filters: tuple[object, ...] = ()


@dataclass(frozen=True, slots=True)
class AuthPolicy:
    strategy: str


@dataclass(frozen=True, slots=True)
class RateLimitPolicy:
    limit: int | None = None
    window: str | None = None
    skip: bool = False


@dataclass(frozen=True, slots=True)
class CachePolicy:
    ttl: int


@dataclass(frozen=True, slots=True)
class IdempotencyPolicy:
    key_header: str = "Idempotency-Key"


@dataclass(frozen=True, slots=True)
class AuditPolicy:
    event: str


@dataclass(frozen=True, slots=True)
class DeprecationPolicy:
    since: str | None = None
    sunset: str | None = None
    replacement: str | None = None


@dataclass(frozen=True, slots=True)
class PolicyMetadata:
    """Merged policy declarations for a controller or handler."""

    auth: AuthPolicy | None = None
    public: bool = False
    roles: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
    rate_limit: RateLimitPolicy | None = None
    cache: CachePolicy | None = None
    idempotency: IdempotencyPolicy | None = None
    audit: AuditPolicy | None = None
    owner: str | None = None
    deprecation: DeprecationPolicy | None = None


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


def set_controller_policy_metadata(controller_cls: ClassT, metadata: PolicyMetadata) -> ClassT:
    setattr(controller_cls, CONTROLLER_POLICY_ATTR, metadata)
    return controller_cls


def get_controller_policy_metadata(
    controller_cls: type[object], *, inherit: bool = False
) -> PolicyMetadata | None:
    metadata = _get_metadata(controller_cls, CONTROLLER_POLICY_ATTR, inherit=inherit)
    return metadata if isinstance(metadata, PolicyMetadata) else None


def set_handler_policy_metadata(handler: FunctionT, metadata: PolicyMetadata) -> FunctionT:
    setattr(handler, HANDLER_POLICY_ATTR, metadata)
    return handler


def get_handler_policy_metadata(handler: object) -> PolicyMetadata | None:
    unwrapped_handler = _unwrap_handler(handler)
    if unwrapped_handler is None:
        return None

    metadata = getattr(unwrapped_handler, HANDLER_POLICY_ATTR, None)
    return metadata if isinstance(metadata, PolicyMetadata) else None


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


def extend_controller_policy_metadata(
    controller_cls: ClassT,
    *,
    auth: AuthPolicy | None = None,
    public: bool | None = None,
    roles: tuple[str, ...] = (),
    permissions: tuple[str, ...] = (),
    rate_limit: RateLimitPolicy | None = None,
    cache: CachePolicy | None = None,
    idempotency: IdempotencyPolicy | None = None,
    audit: AuditPolicy | None = None,
    owner: str | None = None,
    deprecation: DeprecationPolicy | None = None,
) -> ClassT:
    existing_metadata = get_controller_policy_metadata(controller_cls) or PolicyMetadata()
    merged_metadata = merge_policy_metadata(
        existing_metadata,
        PolicyMetadata(
            auth=auth,
            public=public if public is not None else False,
            roles=roles,
            permissions=permissions,
            rate_limit=rate_limit,
            cache=cache,
            idempotency=idempotency,
            audit=audit,
            owner=owner,
            deprecation=deprecation,
        ),
    )
    return set_controller_policy_metadata(controller_cls, merged_metadata)


def extend_handler_policy_metadata(
    handler: FunctionT,
    *,
    auth: AuthPolicy | None = None,
    public: bool | None = None,
    roles: tuple[str, ...] = (),
    permissions: tuple[str, ...] = (),
    rate_limit: RateLimitPolicy | None = None,
    cache: CachePolicy | None = None,
    idempotency: IdempotencyPolicy | None = None,
    audit: AuditPolicy | None = None,
    owner: str | None = None,
    deprecation: DeprecationPolicy | None = None,
) -> FunctionT:
    existing_metadata = get_handler_policy_metadata(handler) or PolicyMetadata()
    merged_metadata = merge_policy_metadata(
        existing_metadata,
        PolicyMetadata(
            auth=auth,
            public=public if public is not None else False,
            roles=roles,
            permissions=permissions,
            rate_limit=rate_limit,
            cache=cache,
            idempotency=idempotency,
            audit=audit,
            owner=owner,
            deprecation=deprecation,
        ),
    )
    return set_handler_policy_metadata(handler, merged_metadata)


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


def merge_policy_metadata(*metadata_items: PolicyMetadata) -> PolicyMetadata:
    """Merge policy metadata while preserving declaration order."""

    auth: AuthPolicy | None = None
    public = False
    roles: list[str] = []
    permissions: list[str] = []
    rate_limit: RateLimitPolicy | None = None
    cache: CachePolicy | None = None
    idempotency: IdempotencyPolicy | None = None
    audit: AuditPolicy | None = None
    owner: str | None = None
    deprecation: DeprecationPolicy | None = None

    for metadata in metadata_items:
        if metadata.auth is not None:
            auth = metadata.auth
        public = public or metadata.public
        roles.extend(metadata.roles)
        permissions.extend(metadata.permissions)
        if metadata.rate_limit is not None:
            if rate_limit is None:
                rate_limit = metadata.rate_limit
            else:
                rate_limit = RateLimitPolicy(
                    limit=(
                        metadata.rate_limit.limit
                        if metadata.rate_limit.limit is not None
                        else rate_limit.limit
                    ),
                    window=(
                        metadata.rate_limit.window
                        if metadata.rate_limit.window is not None
                        else rate_limit.window
                    ),
                    skip=rate_limit.skip or metadata.rate_limit.skip,
                )
        if metadata.cache is not None:
            cache = metadata.cache
        if metadata.idempotency is not None:
            idempotency = metadata.idempotency
        if metadata.audit is not None:
            audit = metadata.audit
        if metadata.owner is not None:
            owner = metadata.owner
        if metadata.deprecation is not None:
            deprecation = metadata.deprecation

    return PolicyMetadata(
        auth=auth,
        public=public,
        roles=tuple(roles),
        permissions=tuple(permissions),
        rate_limit=rate_limit,
        cache=cache,
        idempotency=idempotency,
        audit=audit,
        owner=owner,
        deprecation=deprecation,
    )
