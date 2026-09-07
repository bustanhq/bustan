"""Policy decorators and metadata helpers."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar, cast

from ..kernel.errors import InvalidPipelineError
from ..kernel.utils import _unwrap_handler
from ..pipeline.metadata import (
    AuthPolicy,
    DeprecationPolicy,
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
    """Refuse to decorate: this framework does not cache responses.

    Nothing in the request path stores or serves a cached response, so a route marked
    as cached would be recomputed on every request while reading, to anyone who opens
    the file, as though it were not. Declaring the policy therefore fails where it is
    written rather than in production, and it fails while the application is being
    built rather than once it is serving. Cache in front of the application, or inside
    the handler, until this framework can do it.
    """

    raise InvalidPipelineError(
        "Cache is not implemented: no response is cached, so the decorator would be "
        "inert. Remove it and cache in front of the application or inside the handler."
    )


def Idempotent(*, key_header: str = "Idempotency-Key") -> Callable[[DecoratedT], DecoratedT]:
    """Refuse to decorate: this framework does not deduplicate idempotency keys.

    No key is stored and no repeated request is recognised, so a route marked as
    idempotent would execute its side effect once per retry while reading as though it
    executed once in total. Declaring the policy therefore fails where it is written
    rather than in production, and it fails while the application is being built rather
    than once it is serving. Deduplicate inside the handler, against whatever store
    already holds the side effect, until this framework can do it.
    """

    raise InvalidPipelineError(
        "Idempotent is not implemented: no idempotency key is stored or compared, so "
        "the decorator would be inert. Remove it and deduplicate inside the handler."
    )


def Audit(*, event: str) -> Callable[[DecoratedT], DecoratedT]:
    """Refuse to decorate: this framework writes no audit record.

    Nothing observes the request and nothing writes anywhere, so a route marked as
    audited would leave no trace of who called it while reading as though every call
    were on record. That is the most expensive way for this gap to be discovered, which
    is why declaring the policy fails where it is written rather than in production,
    and fails while the application is being built rather than once it is serving.
    Write the record from the handler, or from an interceptor of your own, until this
    framework can do it.
    """

    raise InvalidPipelineError(
        "Audit is not implemented: no audit record is written, so the decorator would "
        "be inert and the route would leave no audit trail. Remove it and write the "
        "record from the handler or from an interceptor."
    )


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
