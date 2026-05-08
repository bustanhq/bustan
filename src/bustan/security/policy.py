"""Policy decorators and metadata helpers."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar, cast

from ..core.errors import InvalidPipelineError
from ..core.utils import _unwrap_handler
from ..pipeline.metadata import (
    AuditPolicy,
    AuthPolicy,
    CachePolicy,
    DeprecationPolicy,
    IdempotencyPolicy,
    RateLimitPolicy,
    extend_controller_policy_metadata,
    extend_handler_policy_metadata,
)

DecoratedT = TypeVar("DecoratedT", bound=object)


def Auth(strategy: str) -> Callable[[DecoratedT], DecoratedT]:
    return _policy_decorator(auth=AuthPolicy(strategy=strategy))


def Public() -> Callable[[DecoratedT], DecoratedT]:
    return _policy_decorator(public=True)


def Roles(*roles: str) -> Callable[[DecoratedT], DecoratedT]:
    return _policy_decorator(roles=tuple(roles))


def Permissions(*permissions: str) -> Callable[[DecoratedT], DecoratedT]:
    return _policy_decorator(permissions=tuple(permissions))


def RateLimit(*, limit: int, window: str) -> Callable[[DecoratedT], DecoratedT]:
    return _policy_decorator(rate_limit=RateLimitPolicy(limit=limit, window=window))


def Cache(*, ttl: int) -> Callable[[DecoratedT], DecoratedT]:
    return _policy_decorator(cache=CachePolicy(ttl=ttl))


def Idempotent(*, key_header: str = "Idempotency-Key") -> Callable[[DecoratedT], DecoratedT]:
    return _policy_decorator(idempotency=IdempotencyPolicy(key_header=key_header))


def Audit(*, event: str) -> Callable[[DecoratedT], DecoratedT]:
    return _policy_decorator(audit=AuditPolicy(event=event))


def Owner(name: str) -> Callable[[DecoratedT], DecoratedT]:
    return _policy_decorator(owner=name)


def DeprecatedRoute(
    *,
    since: str | None = None,
    sunset: str | None = None,
    replacement: str | None = None,
) -> Callable[[DecoratedT], DecoratedT]:
    return _policy_decorator(
        deprecation=DeprecationPolicy(
            since=since,
            sunset=sunset,
            replacement=replacement,
        )
    )


def _policy_decorator(
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
) -> Callable[[DecoratedT], DecoratedT]:
    def decorate(target: DecoratedT) -> DecoratedT:
        if isinstance(target, type):
            return cast(
                DecoratedT,
                extend_controller_policy_metadata(
                    target,
                    auth=auth,
                    public=public,
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

        handler_function = _unwrap_handler(target)
        if handler_function is None:
            raise InvalidPipelineError(
                "Policy decorators can only decorate controller classes or handler callables"
            )

        extend_handler_policy_metadata(
            handler_function,
            auth=auth,
            public=public,
            roles=roles,
            permissions=permissions,
            rate_limit=rate_limit,
            cache=cache,
            idempotency=idempotency,
            audit=audit,
            owner=owner,
            deprecation=deprecation,
        )
        return target

    return decorate


__all__ = (
    "Audit",
    "Auth",
    "Cache",
    "DeprecatedRoute",
    "Idempotent",
    "Owner",
    "Permissions",
    "Public",
    "RateLimit",
    "Roles",
)