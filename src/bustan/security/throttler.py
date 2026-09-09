"""Sliding-window throttling guard and dynamic module."""

from __future__ import annotations

import math
import time
from collections import OrderedDict, deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from ipaddress import IPv4Address, IPv4Network, IPv6Address, IPv6Network, ip_address, ip_network
from typing import Protocol, runtime_checkable

from ..common.decorators.injectable import Injectable
from ..common.types import ExistingProvider, FactoryProvider, ValueProvider
from ..contracts import HttpResponse, RateLimitDecision
from ..kernel.errors import InvalidPipelineError
from ..kernel.ioc.tokens import APP_GUARD, InjectionToken
from ..kernel.module.decorators import Module
from ..kernel.module.dynamic import DynamicModule
from ..pipeline.context import ExecutionContext
from ..pipeline.guards import Guard
from ..pipeline.metadata import RateLimitPolicy, extend_handler_policy_metadata

THROTTLER_TTL = InjectionToken[int]("THROTTLER_TTL")
THROTTLER_LIMIT = InjectionToken[int]("THROTTLER_LIMIT")
THROTTLER_STORAGE = InjectionToken["ThrottlerStorage"]("THROTTLER_STORAGE")
THROTTLER_KEY_RESOLVER = InjectionToken["ThrottlerKeyResolver"]("THROTTLER_KEY_RESOLVER")
SKIP_THROTTLE_ATTR = "__bustan_skip_throttle__"

# An unauthenticated caller chooses the key it is counted under by choosing where it
# connects from, so the number of live keys is capped rather than left to the caller.
DEFAULT_THROTTLER_MAX_KEYS = 10_000

_FORWARDED_FOR_HEADER = "x-forwarded-for"
_UNKNOWN_CLIENT_KEY = "throttle:unknown"

# A route that declares its own window is counted apart from the application-wide one,
# so the two cannot share a key and spend each other's allowance.
_ROUTE_KEY_PREFIX = "route"
_WINDOW_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}

ThrottlerKeyResolver = Callable[[ExecutionContext], str]

_ProxyNetwork = IPv4Network | IPv6Network
_ClientAddress = IPv4Address | IPv6Address


@dataclass(frozen=True, slots=True)
class ThrottleState:
    """What a throttling store knows about one key once it has counted a request.

    ``count`` is how many requests the key is answerable for inside the window, the
    request just counted included. It exceeds the limit by exactly one when the request
    was refused, because a refused request is not added to the window: refusing a caller
    must not lengthen the wait it is already serving.

    ``reset_after`` is whole seconds until the oldest request still inside the window
    leaves it, which is the moment ``count`` next falls. It is therefore also how long a
    refused caller must wait before a request is accepted, and it is what the guard
    sends as ``Retry-After``. It is ``0`` when the key has nothing counted against it,
    and it never exceeds the window: a caller told to wait longer than the window it is
    measured against has been told something that cannot be true.
    """

    count: int
    reset_after: int


@runtime_checkable
class ThrottlerStorage(Protocol):
    """Where the throttler keeps its per-key request windows.

    Implement this to count requests somewhere every worker process can see, which is
    what makes a configured limit mean the same thing behind a load balancer as it does
    on one process: the in-process default counts each worker separately, so N workers
    allow N times the limit. The method is asynchronous so an implementation backed by a
    network service does not block the event loop while it waits.

    An implementation must treat one call as one request: count it, and report the state
    of the key afterwards. It must not add the request to the window when the window is
    already full, so that a refused caller does not extend its own wait. Where several
    processes share the store, counting and reporting have to happen as one atomic
    operation, or two workers racing on the same key will both be told they are within
    the limit.
    """

    async def count_request(self, key: str, ttl: int, limit: int) -> ThrottleState: ...


@dataclass
class InMemoryThrottlerStorage:
    """In-process sliding-window throttling storage with a bounded key set.

    Counts requests in a sliding window: a key is answerable for the requests it made in
    the last ``ttl`` seconds, measured from now, rather than for the requests it made in
    a calendar window that resets on a boundary. A fixed window lets a caller spend its
    whole allowance just before a boundary and its whole allowance again just after, so
    twice the limit passes in an instant that straddles the boundary; a sliding window
    has no boundary to straddle.

    Memory is bounded whatever the caller does. A caller that rotates source addresses
    creates a key per address, so the store holds at most ``max_keys`` of them and
    discards the least recently used beyond that; a key whose requests have all left the
    window is dropped outright. A refused request is never recorded, so a key holds at
    most ``limit`` timestamps. The store therefore never holds more than
    ``max_keys * limit`` timestamps, no matter how many distinct keys arrive.

    Evicting a key forgets what its caller has spent, so ``max_keys`` has to be
    comfortably above the number of callers expected in one window; a caller whose key
    is evicted starts again with a full allowance.

    Requests are aged by the difference between two readings of ``clock``, which must
    therefore be monotonic, as the default is. A clock that can step backwards would let
    a key report a window longer than the one it is measured against.
    """

    max_keys: int = DEFAULT_THROTTLER_MAX_KEYS
    clock: Callable[[], float] = time.monotonic
    _windows: OrderedDict[str, deque[float]] = field(
        default_factory=OrderedDict[str, "deque[float]"], init=False
    )

    def __post_init__(self) -> None:
        if self.max_keys < 1:
            raise ValueError("InMemoryThrottlerStorage requires max_keys of at least 1")

    def __len__(self) -> int:
        """Return how many keys the store is currently holding a window for."""

        return len(self._windows)

    async def count_request(self, key: str, ttl: int, limit: int) -> ThrottleState:
        """Count one request against *key* and report the key's state afterwards."""

        now = self.clock()
        window = self._windows.get(key)
        if window is None:
            window = deque()
        else:
            self._windows.move_to_end(key)

        cutoff = now - ttl
        while window and window[0] <= cutoff:
            window.popleft()

        if len(window) < limit:
            window.append(now)
            count = len(window)
        else:
            count = len(window) + 1

        if window:
            self._windows[key] = window
            self._windows.move_to_end(key)
            # From the age of the oldest request, never from the clock reading plus
            # the window. A clock reading whose window crosses a binade boundary
            # cannot hold the sum to the same precision as itself, so the sum rounds
            # and the difference comes back a fraction over the window, which the
            # ceiling turns into a whole second too many. Subtracting two readings
            # is exact over any interval a window spans, and is exactly zero for the
            # request just counted, so a fresh key reports the whole window and no
            # key can ever be told to wait longer than one.
            reset_after = max(0, math.ceil(ttl - (now - window[0])))
        else:
            self._windows.pop(key, None)
            reset_after = 0

        while len(self._windows) > self.max_keys:
            self._windows.popitem(last=False)

        return ThrottleState(count=count, reset_after=reset_after)


def SkipThrottle(handler):
    """Mark a route handler as exempt from throttling."""
    setattr(handler, SKIP_THROTTLE_ATTR, True)
    extend_handler_policy_metadata(handler, rate_limit=RateLimitPolicy(skip=True))
    return handler


@Injectable
class ThrottlerGuard(Guard):
    """Guard that rejects requests after the configured limit is exceeded."""

    def __init__(
        self,
        storage: ThrottlerStorage,
        ttl: int,
        limit: int,
        key_resolver: ThrottlerKeyResolver,
    ) -> None:
        self.storage = storage
        self.ttl = ttl
        self.limit = limit
        self.key_resolver = key_resolver

    async def can_activate(self, context: ExecutionContext) -> bool:
        request = context.request
        if request is None:
            raise RuntimeError("ThrottlerGuard requires an active HTTP request")

        policy_plan = context.get_policy_plan()
        if getattr(getattr(policy_plan, "rate_limit", None), "skip", False):
            return True

        handler = getattr(context.route, "handler", None)
        if handler is None:
            handler = getattr(context.get_handler(), "__func__", context.get_handler())
        if getattr(handler, SKIP_THROTTLE_ATTR, False):
            return True

        limit, ttl, key = self._resolve_budget(context, handler)
        state = await self.storage.count_request(key, ttl, limit)
        exceeded = state.count > limit
        request.slots.rate_limit = RateLimitDecision(
            limit=limit,
            remaining=max(0, limit - state.count),
            reset=state.reset_after,
            exceeded=exceeded,
        )
        if exceeded:
            _set_retry_after(context, state.reset_after)
        return not exceeded

    def _resolve_budget(self, context: ExecutionContext, handler: object) -> tuple[int, int, str]:
        """Return the limit, the window and the key one request is counted against.

        A route that declares its own limit and window is counted against those, under a
        key of its own, instead of against the application-wide window rather than as
        well as it. Counting one arriving request against both would spend two
        allowances for it, which is not one request counted once; and a single key
        cannot hold two windows of different lengths, since the window a key is measured
        against is whichever one the caller counting against it named. A route that
        declares no limit is counted exactly as it was before: the application-wide
        limit and window, under the key the resolver returns.
        """

        caller_key = self.key_resolver(context)
        policy = getattr(context.get_policy_plan(), "rate_limit", None)
        limit = getattr(policy, "limit", None)
        window = getattr(policy, "window", None)
        if not isinstance(limit, int) or not isinstance(window, str):
            return self.limit, self.ttl, caller_key

        module_name = getattr(handler, "__module__", "")
        qualified_name = getattr(handler, "__qualname__", "")
        route_key = f"{caller_key}:{_ROUTE_KEY_PREFIX}:{module_name}.{qualified_name}"
        return limit, _window_seconds(window), route_key


@Module()
class _ThrottlerModuleBase:
    pass


class ThrottlerModule:
    """Factory for throttling support."""

    @staticmethod
    def for_root(
        *,
        ttl: int,
        limit: int,
        key_resolver: ThrottlerKeyResolver | None = None,
        storage: ThrottlerStorage | None = None,
        trusted_proxies: Sequence[str] = (),
        max_keys: int = DEFAULT_THROTTLER_MAX_KEYS,
    ) -> DynamicModule:
        """Return a module that counts every request and refuses callers over the limit.

        ``ttl`` is the window in seconds and ``limit`` the requests one key may make
        inside it. ``storage`` counts the requests; leave it unset for an in-process
        store holding at most ``max_keys`` keys, and pass a shared implementation of
        ``ThrottlerStorage`` when the application runs as more than one worker, because
        an in-process store counts each worker separately and N workers then allow N
        times the limit.

        ``trusted_proxies`` is the list of addresses and CIDR blocks that are allowed to
        name the caller on the application's behalf, given as the peers the application
        accepts connections from. It is empty by default, which counts every request
        under the address it arrived from and ignores forwarding headers entirely. Set
        it to the load balancer the application actually sits behind, never to a wide
        block: any peer in this list can put any address in ``X-Forwarded-For`` and be
        counted as that caller, so listing a peer an attacker can connect from lets that
        attacker spend another caller's allowance or evade its own limit.

        ``key_resolver`` replaces the derivation of the key altogether. A resolver of
        your own is responsible for its own trust decisions, so ``trusted_proxies`` is
        not consulted when one is given.
        """

        # An empty in-memory store is falsy, so the default is chosen on identity.
        resolved_storage = (
            InMemoryThrottlerStorage(max_keys=max_keys) if storage is None else storage
        )
        resolved_resolver = (
            _client_address_key_resolver(trusted_proxies) if key_resolver is None else key_resolver
        )
        return DynamicModule(
            module=_ThrottlerModuleBase,
            providers=(
                ValueProvider(provide=THROTTLER_TTL, use_value=ttl),
                ValueProvider(provide=THROTTLER_LIMIT, use_value=limit),
                ValueProvider(provide=THROTTLER_STORAGE, use_value=resolved_storage),
                ValueProvider(provide=THROTTLER_KEY_RESOLVER, use_value=resolved_resolver),
                FactoryProvider(
                    provide=ThrottlerGuard,
                    use_factory=ThrottlerGuard,
                    inject=(
                        THROTTLER_STORAGE,
                        THROTTLER_TTL,
                        THROTTLER_LIMIT,
                        THROTTLER_KEY_RESOLVER,
                    ),
                ),
                ExistingProvider(provide=APP_GUARD, use_existing=ThrottlerGuard),
            ),
            exports=(ThrottlerGuard, THROTTLER_STORAGE),
        )


def _window_seconds(window: str) -> int:
    """Return the length in seconds of a window a route declared.

    A window is a whole number of seconds, or a whole number followed by ``s``, ``m``,
    ``h`` or ``d``. One that cannot be read is refused rather than defaulted, because a
    route whose declared window is unintelligible would otherwise be served as though it
    had declared no limit at all, which is the outcome a declared limit exists to
    prevent.
    """

    text = window.strip().lower()
    unit = _WINDOW_UNIT_SECONDS.get(text[-1:])
    digits = text[:-1] if unit is not None else text
    if not digits.isascii() or not digits.isdigit():
        raise InvalidPipelineError(
            f"Rate limit window {window!r} is not a whole number of seconds, "
            "optionally suffixed with s, m, h or d"
        )

    seconds = int(digits) * (unit if unit is not None else 1)
    if seconds < 1:
        raise InvalidPipelineError(f"Rate limit window {window!r} is not at least one second")
    return seconds


def _set_retry_after(context: ExecutionContext, reset_after: int) -> None:
    """Tell a refused caller when to come back, on whichever response is written.

    The header goes on the per-request response the runtime merges into whatever it
    finally writes, so it survives the refusal being turned into a 429 by an exception
    filter rather than being returned by a handler.
    """

    response = context.response
    if isinstance(response, HttpResponse):
        response.headers["Retry-After"] = str(max(1, reset_after))


def _client_address_key_resolver(trusted_proxies: Sequence[str]) -> ThrottlerKeyResolver:
    """Return a resolver keying requests on the caller's address."""

    networks = tuple(ip_network(entry, strict=False) for entry in trusted_proxies)

    def resolve(context: ExecutionContext) -> str:
        request = context.request
        if request is None:
            return _UNKNOWN_CLIENT_KEY

        client = request.client
        peer = client.host if client is not None else None
        if peer is None:
            return _UNKNOWN_CLIENT_KEY
        if not _is_trusted(peer, networks):
            return f"throttle:{peer}"

        forwarded = request.headers.get(_FORWARDED_FOR_HEADER)
        claimed = _forwarded_client(forwarded, networks) if forwarded else None
        return f"throttle:{claimed or peer}"

    return resolve


def _forwarded_client(forwarded: str, networks: tuple[_ProxyNetwork, ...]) -> str | None:
    """Return the caller named by a forwarding header, or ``None`` to distrust it.

    The header is only ever read once the peer that sent it is trusted, and it is read
    from the right, because each proxy appends the address it saw and only the entries a
    trusted proxy wrote are worth anything. The rightmost entry that is not itself a
    trusted proxy is the caller. Scanning stops at the first entry that is not an
    address, since a chain that stops parsing cannot be attributed any further, and the
    entry is returned in its canonical form so that two spellings of one address cannot
    be made to occupy two windows.
    """

    for entry in reversed(forwarded.split(",")):
        address = _parse_address(entry)
        if address is None:
            return None
        if not any(address in network for network in networks):
            return address.compressed
    return None


def _is_trusted(host: str, networks: tuple[_ProxyNetwork, ...]) -> bool:
    address = _parse_address(host)
    if address is None:
        return False
    return any(address in network for network in networks)


def _parse_address(value: str) -> _ClientAddress | None:
    """Parse one forwarding-chain or peer entry, tolerating a port and IPv6 brackets."""

    candidate = value.strip()
    if candidate.startswith("["):
        candidate = candidate[1:].partition("]")[0]
    elif candidate.count(":") == 1:
        candidate = candidate.partition(":")[0]
    try:
        return ip_address(candidate)
    except ValueError:
        return None
