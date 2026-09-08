"""Policy decorators and metadata helpers."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar, cast

from ..kernel.errors import InvalidPipelineError
from ..kernel.utils import _unwrap_handler
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
from .throttler import _window_seconds

DecoratedT = TypeVar("DecoratedT", bound=object)


def Auth(strategy: str) -> Callable[[DecoratedT], DecoratedT]:
    """Serve this route only to a caller the named authentication strategy identifies.

    ``strategy`` selects one authenticator out of the registry a module binds under
    ``AUTHENTICATOR_REGISTRY``. It runs before the handler, and the principal it
    returns is what ``Roles`` and ``Permissions`` are then checked against. A caller it
    does not identify is refused with the challenge that says how to present an
    identity. A strategy the registry does not name refuses every caller of the route
    whatever it sends, so it is reported as an application fault rather than as a
    refusal of the caller, and the reason is written to the log rather than to them.
    """

    return _policy_decorator(auth=AuthPolicy(strategy=strategy))


def Public() -> Callable[[DecoratedT], DecoratedT]:
    """Serve this route to anybody, whatever the controller around it requires.

    Authentication and the role and permission checks are skipped, so nothing about
    the caller is established and no principal reaches the handler. Written on a
    handler it outranks the controller, which is what makes one open route on an
    otherwise authenticated controller expressible; written beside an access
    requirement at the same level it is contradictory and refused while the routes are
    compiled. Guards the application registers itself still run: this waives the policy
    these decorators declare, not every gate in front of the handler.
    """

    return _policy_decorator(public=True)


def Roles(*roles: str) -> Callable[[DecoratedT], DecoratedT]:
    """Serve this route only to a caller holding every one of these roles.

    The roles are read off the principal the route's authentication produced, and all
    of them must be held: naming two means both, never either. Roles written on the
    controller and on the handler add up rather than replace one another, so a handler
    narrows what its controller requires and can never widen it. A caller carrying an
    identity that lacks a role is refused as unable to retry, because presenting the
    same identity again would change nothing; one carrying no identity is asked for one.
    """

    return _policy_decorator(roles=tuple(roles))


def Permissions(*permissions: str) -> Callable[[DecoratedT], DecoratedT]:
    """Serve this route only to a caller holding every one of these permissions.

    Read off the principal and accumulated across the controller and the handler
    exactly as ``Roles`` are, and refused the same way. What separates the two is only
    what an application chooses to put in each: the container never interprets either.
    """

    return _policy_decorator(permissions=tuple(permissions))


def RateLimit(*, limit: int, window: str) -> Callable[[DecoratedT], DecoratedT]:
    """Count this route's callers against a budget of its own, not the shared one.

    ``limit`` requests are allowed per ``window``, written as a whole number of seconds
    or a whole number followed by ``s``, ``m``, ``h`` or ``d``. The route is counted
    under a key of its own, so a request spends this budget instead of the
    application-wide one rather than as well as it, and a caller over the limit is
    refused with the headers that say how much is left and when to retry.

    The counting is the throttler's. An application that has not installed throttling
    records this policy and enforces nothing, so a route that must be bounded needs
    both.
    """

    # Reading the window here refuses one that cannot be read where it was written, while
    # the application is being built. Left to the guard that enforces it, the same refusal
    # reaches the caller as a server fault, on every request the route ever serves, and
    # says nothing at the place the mistake was made.
    _window_seconds(window)
    return _policy_decorator(rate_limit=RateLimitPolicy(limit=limit, window=window))


def Cache(*, ttl: int) -> Callable[[DecoratedT], DecoratedT]:
    """No response is cached in this version; the decorator only records the policy.

    ``ttl`` reaches the route's compiled policy plan, and nothing in the request path
    acts on it, so a route marked with this decorator is recomputed on every request.
    Cache in front of the application, or inside the handler, for as long as that is so.
    """

    return _policy_decorator(cache=CachePolicy(ttl=ttl))


def Idempotent(*, key_header: str = "Idempotency-Key") -> Callable[[DecoratedT], DecoratedT]:
    """No idempotency key is stored or compared in this version; the policy is recorded.

    ``key_header`` reaches the route's compiled policy plan, and nothing in the request
    path acts on it, so a retried request runs the handler again and its side effect
    happens again. Deduplicate inside the handler, against the store that already holds
    the side effect, for as long as that is so.
    """

    return _policy_decorator(idempotency=IdempotencyPolicy(key_header=key_header))


def Audit(*, event: str) -> Callable[[DecoratedT], DecoratedT]:
    """No audit record is written in this version; the decorator only records the policy.

    ``event`` reaches the route's compiled policy plan, and nothing in the request path
    acts on it, so a route marked with this decorator leaves no trace of who called it.
    Write the record from the handler, or from an interceptor of your own, for as long
    as that is so.
    """

    return _policy_decorator(audit=AuditPolicy(event=event))


def Owner(name: str) -> Callable[[DecoratedT], DecoratedT]:
    """Record which team or person answers for this route.

    ``name`` is free text the framework only carries. Nothing in the request path reads
    it; it reaches the route's compiled policy plan, and the governance ownership report
    renders it from there, so a route can be traced to whoever maintains it without that
    costing a request anything.
    """

    return _policy_decorator(owner=name)


def DeprecatedRoute(
    *,
    since: str | None = None,
    sunset: str | None = None,
    replacement: str | None = None,
) -> Callable[[DecoratedT], DecoratedT]:
    """Record that this route is going away, and what its callers should move to.

    ``since`` is when it was deprecated, ``sunset`` when it stops being served and
    ``replacement`` what to call instead; all three are free text the framework only
    carries. No response header is written from them and nothing in the request path
    reads them, so a caller learns none of this from the route itself. They reach the
    route's compiled policy plan, and the governance ownership report renders them for
    whoever is planning the removal.
    """

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
