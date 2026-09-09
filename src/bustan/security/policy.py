"""Policy decorators, and the interceptors that carry out the three with a behaviour.

Most of these decorators declare something a stage elsewhere enforces: the policy guard
reads what ``Auth``, ``Public``, ``Roles`` and ``Permissions`` declare, the throttler
guard reads what ``RateLimit`` declares, and the governance report reads what ``Owner``
and ``DeprecatedRoute`` declare. ``Cache``, ``Idempotent`` and ``Audit`` have no stage of
their own, so each attaches the interceptor that carries it out to the route it is
written on, and that interceptor reads the route's compiled policy plan the same way the
guards read theirs. Enforcement sits beside the declaration for the same reason it does
in the throttler: a reader asking what a decorator does finds the answer in one file.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic
from typing import TypeVar, cast

from ..kernel.errors import InvalidPipelineError
from ..kernel.utils import _unwrap_handler
from ..observability.logger import Logger, LogLevel
from ..observability.observability import build_route_labels
from ..pipeline.context import ExecutionContext
from ..pipeline.interceptors import CallHandler, Interceptor
from ..pipeline.metadata import (
    AuditPolicy,
    AuthPolicy,
    CachePolicy,
    DeprecationPolicy,
    IdempotencyPolicy,
    RateLimitPolicy,
    extend_controller_pipeline_metadata,
    extend_controller_policy_metadata,
    extend_handler_pipeline_metadata,
    extend_handler_policy_metadata,
)
from .throttler import _window_seconds

DecoratedT = TypeVar("DecoratedT", bound=object)

# The methods a cached answer may be replayed for. Replaying anything else would skip a
# change the caller asked for, so the set is the two methods HTTP defines as reads.
_SAFE_METHODS = frozenset({"GET", "HEAD"})

# What one decorated route may hold. A caller chooses the entry its request is kept
# under by choosing the path, the query string and the key it sends, so the count is
# capped rather than left to whoever is calling; the oldest entry goes when a new one
# arrives at the cap. Both numbers are quoted in the public docstrings below, so a
# change here is a change there.
CACHE_ENTRY_LIMIT = 512
IDEMPOTENCY_KEY_LIMIT = 1024

# How long a recorded result answers for the key that produced it. Quoted in
# ``Idempotent``'s docstring as twenty-four hours.
IDEMPOTENCY_RETENTION_SECONDS = 24 * 60 * 60

# The context label every audit record is written under, which is what a reader filters
# the framework's records by to see the trail on its own.
AUDIT_LOG_CONTEXT = "Audit"


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
    """Answer a repeated read with what the last one computed, until it goes stale.

    ``ttl`` is how many whole seconds an answer stays usable, counted from when it was
    computed, and must be at least one. A request matching an answer still inside its
    ttl is served from it and the handler does not run at all; anything else runs the
    handler and keeps what it returned.

    Only ``GET`` and ``HEAD`` are served this way, because replaying a method that is
    allowed to change something would skip the change. Answers are kept apart by the
    route, by the exact path and query string the caller asked for, and by the identity
    the request was authorised under, so one caller's answer is never handed to another
    and two different queries never share one. Headers are no part of that, so a route
    whose body varies by header, by ``Accept`` or by a language, must not be cached
    here. A handler returning a response object or a stream rather than a value is
    refused this decorator while the application is built, because such a body can only
    be read once.

    Only the handler is skipped. Everything in front of it still runs, so a caller who
    should be refused is still refused, on the request that would have been served from
    the cache as much as on the one that filled it.

    The store is in the process and lives on the decorator: it is shared by every
    application in the process that serves this route, is never shared between
    processes or across a restart, and holds at most 512 answers per decorated route,
    dropping the oldest when a new one arrives at that limit. An application needing a
    cache any of that is untrue of needs one of its own, in front of the process.
    """

    if ttl < 1:
        # Refused where it was written, while the application is being built. A ttl
        # that expires an answer the moment it is stored is a route that reads as
        # cached and is recomputed every time, and nothing later in the request would
        # ever have cause to say so.
        raise InvalidPipelineError(f"Cache ttl {ttl!r} is not at least one second")

    return _policy_decorator(cache=CachePolicy(ttl=ttl), interceptors=(_CachedAnswers(),))


def Idempotent(*, key_header: str = "Idempotency-Key") -> Callable[[DecoratedT], DecoratedT]:
    """Answer a retry carrying a key already seen with what the first attempt returned.

    ``key_header`` names the header a caller puts its key in. The first request
    presenting a key runs the handler and its result is recorded under that key; a
    later request presenting the same key to the same route and path is answered from
    the recording and the handler does not run, so the side effect happens once however
    many times the request is retried. The path is part of the key, so one key
    presented against two different resources is two attempts rather than one.

    A request carrying no such header is not deduplicated and runs like any other,
    because a key is the only thing that tells one attempt from a retry of it. Two
    requests presenting the same key at the same time both run: the recording is made
    when the first finishes, and until then the second has nothing to find. A handler
    returning a response object or a stream rather than a value is refused this
    decorator while the application is built, because such a body can only be read once.

    A recording answers for twenty-four hours, after which the same key is a fresh
    attempt. The store is in the process and lives on the decorator: it is shared by
    every application in the process that serves this route, is never shared between
    processes or across a restart, and holds at most 1024 keys per decorated route,
    dropping the oldest when a new one arrives at that limit. An application that must
    deduplicate across its workers, or across a restart, needs a store of its own.
    """

    return _policy_decorator(
        idempotency=IdempotencyPolicy(key_header=key_header),
        interceptors=(_RecordedAttempts(),),
    )


def Audit(*, event: str) -> Callable[[DecoratedT], DecoratedT]:
    """Write a record of who called this route, every time it is called.

    ``event`` names what the record is a record of, and is what a reader searches the
    trail for. One record is written once the handler has finished, whether it returned
    or raised, carrying that name, whether the call succeeded, the controller, route,
    operation and version it reached, the identity it was authorised under when it was
    authorised, and the correlation and trace ids of the request it belongs to.

    Nothing the caller sent is in the record: no header, no body, no query and no path.
    The trail says who called what and when, and a reader who needs what they sent
    follows the correlation id into the request's own records rather than finding a
    copy of it here.

    There is no store. The record is written through the framework's logger, so it goes
    wherever the application has configured that to write, is redacted by the same
    rules, and is filtered by the same level: records are written at the log level, and
    an application that raises the level above it stops writing them.
    """

    return _policy_decorator(audit=AuditPolicy(event=event), interceptors=(_AuditTrail(),))


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
    interceptors: tuple[object, ...] = (),
) -> Callable[[DecoratedT], DecoratedT]:
    """Return the decorator that records one policy, and attaches whatever carries it out.

    ``interceptors`` is what makes a policy with a behaviour of its own reach the request
    rather than only the plan. They are attached where a controller or a handler declares
    any other interceptor, so the runtime that already resolves and runs those runs these
    too, in the order the decorators were written.
    """

    def decorate(target: DecoratedT) -> DecoratedT:
        if isinstance(target, type):
            controller_cls = extend_controller_policy_metadata(
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
            )
            if interceptors:
                extend_controller_pipeline_metadata(controller_cls, interceptors=interceptors)
            return cast(DecoratedT, controller_cls)

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
        if interceptors:
            extend_handler_pipeline_metadata(handler_function, interceptors=interceptors)
        return target

    return decorate


@dataclass(frozen=True, slots=True)
class _Recorded:
    """One handler result held for replay, and the moment it stops being answerable."""

    value: object
    expires_at: float


class _RecordedResults:
    """The handler results one decorated route may answer with, bounded and timed out.

    An entry is written once and read until it expires, and is never renewed by being
    read, because what a ttl measures is the age of the answer rather than how recently
    somebody wanted it. Entries therefore leave in the order they arrived, which is what
    lets the oldest be dropped from the front when the store is full.

    The bound is what makes the store safe to put in front of an unauthenticated caller:
    the caller chooses what its request is keyed under, so a caller varying the key
    evicts its own earlier entries instead of growing the process. Every operation is
    taken under one lock, because the store is read and written from whichever threads
    happen to be serving requests.
    """

    __slots__ = ("_entries", "_guard", "limit")

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self._entries: OrderedDict[object, _Recorded] = OrderedDict()
        self._guard = threading.Lock()

    def answer(self, key: object) -> _Recorded | None:
        """Return the entry *key* is still answerable by, forgetting an expired one."""

        now = monotonic()
        with self._guard:
            entry = self._entries.get(key)
            if entry is None:
                return None
            if entry.expires_at <= now:
                del self._entries[key]
                return None
            return entry

    def record(self, key: object, value: object, ttl: float) -> None:
        """Hold *value* against *key* for *ttl* seconds, dropping what no longer fits."""

        now = monotonic()
        with self._guard:
            self._entries[key] = _Recorded(value=value, expires_at=now + ttl)
            self._entries.move_to_end(key)
            self._drop_stale(now)

    def _drop_stale(self, now: float) -> None:
        """Drop from the front until nothing has expired there and the limit is kept.

        Only the front is examined. An entry further in can be expired and still be
        held, because reaching it would cost a walk of the whole store on every write;
        it is never answered with, and it leaves as the entries in front of it do.
        """

        entries = self._entries
        while entries:
            oldest = next(iter(entries.values()))
            if len(entries) <= self.limit and oldest.expires_at > now:
                return
            entries.popitem(last=False)


class _CachedAnswers(Interceptor):
    """Answer a repeated read from what the last one computed, without running it again."""

    # A hit answers with a body computed for an earlier request rather than with the
    # one this handler would produce now, so a route whose body can only be read once -
    # a response object, a stream - is refused this while the application is built
    # rather than served a replay of something already consumed.
    mutates_response_body = True

    def __init__(self) -> None:
        self._results = _RecordedResults(CACHE_ENTRY_LIMIT)

    async def intercept(self, context: ExecutionContext, next: CallHandler) -> object:
        ttl = _declared_cache_ttl(context)
        if ttl is None:
            return await next.handle()

        key = _cacheable_key(context)
        if key is None:
            return await next.handle()

        recorded = self._results.answer(key)
        if recorded is not None:
            return recorded.value

        result = await next.handle()
        self._results.record(key, result, ttl)
        return result


class _RecordedAttempts(Interceptor):
    """Answer a retry presenting a key already seen with what the first attempt returned."""

    # A replay answers with the first attempt's body, under the same reasoning the
    # cache above is refused a body that can only be read once.
    mutates_response_body = True

    def __init__(self) -> None:
        self._results = _RecordedResults(IDEMPOTENCY_KEY_LIMIT)

    async def intercept(self, context: ExecutionContext, next: CallHandler) -> object:
        key = _presented_idempotency_key(context)
        if key is None:
            return await next.handle()

        recorded = self._results.answer(key)
        if recorded is not None:
            return recorded.value

        result = await next.handle()
        self._results.record(key, result, IDEMPOTENCY_RETENTION_SECONDS)
        return result


class _AuditTrail(Interceptor):
    """Write one record of the call every time the route it is attached to is served."""

    async def intercept(self, context: ExecutionContext, next: CallHandler) -> object:
        policy = getattr(context.get_policy_plan(), "audit", None)
        if not isinstance(policy, AuditPolicy):
            return await next.handle()
        event = policy.event

        try:
            result = await next.handle()
        except Exception as error:
            # A call that failed is as much a call as one that succeeded, and the
            # attempt is what an audit trail is read for. The record is written before
            # the failure is re-raised so that the answer the caller gets and the trail
            # cannot disagree about whether the route was reached.
            _write_audit_record(context, event, succeeded=False, failure=type(error).__name__)
            raise
        _write_audit_record(context, event, succeeded=True, failure=None)
        return result


def _declared_cache_ttl(context: ExecutionContext) -> int | None:
    """Return the ttl the route's compiled plan declares, or ``None`` when it declares none.

    The plan is read rather than the argument this decorator was given, because the plan
    is where a handler's declaration has already outranked its controller's. A handler
    that shortens what its controller declared is therefore served under its own ttl,
    from the one interceptor the controller attached.
    """

    policy = getattr(context.get_policy_plan(), "cache", None)
    if not isinstance(policy, CachePolicy) or policy.ttl < 1:
        return None
    return policy.ttl


def _cacheable_key(context: ExecutionContext) -> tuple[object, ...] | None:
    """Return what one request may be answered under, or ``None`` when it may not be.

    Nothing is answered from the cache unless everything the answer depends on is in
    the key. A method allowed to change something is not replayed at all; a caller the
    request was authorised for but whose identity cannot be read is not risked against
    another caller's entry; and a transport that does not expose the query string is
    not keyed on a path that two different queries share.
    """

    request = context.request
    if request is None or request.method.upper() not in _SAFE_METHODS:
        return None

    # The neutral URL contract promises a path and nothing else, so a transport that
    # carries no readable query string leaves this request uncacheable rather than
    # sharing one entry between two questions.
    query_string = getattr(request.url, "query_string", None)
    if not isinstance(query_string, str):
        return None

    caller: str | None = None
    principal = context.get_principal()
    if principal is not None:
        identity = getattr(principal, "id", None)
        if not isinstance(identity, str):
            return None
        caller = identity

    return (_route_identity(context), request.method.upper(), request.path, query_string, caller)


def _presented_idempotency_key(context: ExecutionContext) -> tuple[object, ...] | None:
    """Return what one attempt is recorded under, or ``None`` when it presented no key."""

    request = context.request
    if request is None:
        return None

    policy = getattr(context.get_policy_plan(), "idempotency", None)
    if not isinstance(policy, IdempotencyPolicy):
        return None
    header_name = policy.key_header

    # Both transports in this repository match a header without regard to case, and the
    # neutral contract is a plain mapping that need not, so the folded name is tried as
    # well: a key the caller sent must never go unrecognised and let the handler run
    # again for an attempt already made.
    headers = request.headers
    presented = headers.get(header_name) or headers.get(header_name.lower())
    if not presented:
        return None

    return (_route_identity(context), request.method.upper(), request.path, presented)


def _route_identity(context: ExecutionContext) -> tuple[str, str]:
    """Name the handler a request reached, so two routes never share one entry.

    One decorator instance can be written on a controller and so serve every route
    under it, which is why the entry is keyed by the handler rather than left to the
    store the interceptor happens to hold.
    """

    handler = context.get_handler()
    function = getattr(handler, "__func__", handler)
    return (getattr(function, "__module__", ""), getattr(function, "__qualname__", ""))


def _write_audit_record(
    context: ExecutionContext,
    event: str,
    *,
    succeeded: bool,
    failure: str | None,
) -> None:
    """Write one audit record for a route that has just been served.

    The logger is built here rather than held on the interceptor so that the record is
    written at the level and to the destination the application has configured now,
    rather than at whichever was configured when the route was imported.
    """

    fields: dict[str, object] = {
        "event": event,
        "succeeded": succeeded,
        **build_route_labels(context.get_route_contract()),
    }
    principal = context.get_principal()
    identity = getattr(principal, "id", None)
    if isinstance(identity, str):
        fields["principal"] = identity
    if failure is not None:
        fields["failure"] = failure
    Logger(AUDIT_LOG_CONTEXT).record(LogLevel.LOG, event, fields=fields)


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
