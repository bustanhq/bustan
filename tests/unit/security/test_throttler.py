"""Unit tests for the throttler module."""

from __future__ import annotations

import math
from typing import Any, cast

import pytest
from starlette.testclient import TestClient

from bustan import Controller, Get, Module, SkipThrottle, ThrottlerModule, create_app
from bustan.security import RateLimit
from bustan.security.throttler import (
    InMemoryThrottlerStorage,
    ThrottleState,
    _client_address_key_resolver,
)


class _Clock:
    """A monotonic clock a test advances by hand, so no test has to sleep."""

    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _FixedWindowStorage:
    """The storage this ticket replaced, kept here only to be compared against.

    It counts into a window that starts at the first request and resets whole, which is
    the behaviour the sliding window has to be shown to improve on. It is deliberately
    the old algorithm and nothing else.
    """

    def __init__(self, clock: _Clock) -> None:
        self._clock = clock
        self._windows: dict[str, tuple[float, int]] = {}

    async def count_request(self, key: str, ttl: int, limit: int) -> ThrottleState:
        now = self._clock()
        started_at, count = self._windows.get(key, (now, 0))
        if now - started_at >= ttl:
            started_at, count = now, 0
        count += 1
        self._windows[key] = (started_at, count)
        return ThrottleState(count=count, reset_after=max(0, math.ceil(started_at + ttl - now)))


@Controller("/")
class _AppController:
    @Get("/")
    def index(self) -> dict[str, str]:
        return {"status": "ok"}


def _throttled_app(**options: Any) -> Any:
    @Module(imports=[ThrottlerModule.for_root(**options)], controllers=[_AppController])
    class AppModule:
        pass

    return cast(Any, create_app(AppModule))


def test_throttler_module_rejects_requests_above_the_limit() -> None:
    @Controller("/")
    class AppController:
        @Get("/")
        def index(self) -> dict[str, str]:
            return {"status": "ok"}

    @Module(imports=[ThrottlerModule.for_root(ttl=60, limit=1)], controllers=[AppController])
    class AppModule:
        pass

    with TestClient(cast(Any, create_app(AppModule))) as client:
        first = client.get("/")
        second = client.get("/")

    assert first.status_code == 200
    assert first.headers["X-RateLimit-Limit"] == "1"
    assert second.status_code == 429


def test_skip_throttle_decorator_bypasses_the_guard() -> None:
    @Controller("/")
    class AppController:
        @SkipThrottle
        @Get("/")
        def index(self) -> dict[str, str]:
            return {"status": "ok"}

    @Module(imports=[ThrottlerModule.for_root(ttl=60, limit=1)], controllers=[AppController])
    class AppModule:
        pass

    with TestClient(cast(Any, create_app(AppModule))) as client:
        assert client.get("/").status_code == 200
        assert client.get("/").status_code == 200


def test_throttler_module_supports_custom_key_resolution() -> None:
    @Controller("/")
    class AppController:
        @Get("/")
        def index(self) -> dict[str, str]:
            return {"status": "ok"}

    @Module(
        imports=[
            ThrottlerModule.for_root(
                ttl=60,
                limit=1,
                key_resolver=lambda context: (
                    f"client:{context.request.headers.get('x-client-id', 'missing')}"
                ),
            )
        ],
        controllers=[AppController],
    )
    class AppModule:
        pass

    with TestClient(cast(Any, create_app(AppModule))) as client:
        first = client.get("/", headers={"x-client-id": "a"})
        second = client.get("/", headers={"x-client-id": "b"})
        third = client.get("/", headers={"x-client-id": "a"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429


@pytest.mark.anyio
async def test_the_sliding_window_refuses_the_burst_a_fixed_window_admits() -> None:
    """The boundary burst: a whole allowance on each side of a fixed window boundary.

    A caller spends its allowance across the first half-second of a fixed window and its
    allowance again the instant the window rolls over. The two bursts are less than one
    window apart, so twice the limit reaches the application inside a single window's
    worth of time, and a fixed window admits all of it because the boundary fell in
    between. A sliding window measures the last ``ttl`` seconds from now instead of from
    a boundary, so it admits only the one request whose slot has genuinely expired.
    """

    clock = _Clock()
    fixed = _FixedWindowStorage(clock)
    sliding = InMemoryThrottlerStorage(clock=clock)
    ttl, limit = 60, 5
    opened_at = clock.now

    for index in range(limit):
        clock.now = opened_at + index * 0.1
        assert (await fixed.count_request("k", ttl, limit)).count <= limit
        assert (await sliding.count_request("k", ttl, limit)).count <= limit

    # The instant the fixed window that opened with the first request rolls over.
    clock.now = opened_at + ttl

    fixed_admitted = 0
    sliding_admitted = 0
    for _ in range(limit):
        fixed_admitted += (await fixed.count_request("k", ttl, limit)).count <= limit
        sliding_admitted += (await sliding.count_request("k", ttl, limit)).count <= limit

    assert fixed_admitted == limit
    assert sliding_admitted == 1


@pytest.mark.anyio
async def test_memory_stays_bounded_while_a_caller_rotates_keys() -> None:
    """A caller rotating source addresses must not be able to grow the store."""

    clock = _Clock()
    storage = InMemoryThrottlerStorage(max_keys=64, clock=clock)
    observed = []

    for index in range(50_000):
        await storage.count_request(f"throttle:198.51.100.{index}", 60, 5)
        if index % 1_000 == 0:
            observed.append(len(storage))

    assert max(observed) <= 64
    assert len(storage) == 64
    retained = sum(len(window) for window in storage._windows.values())
    assert retained <= 64 * 5


@pytest.mark.anyio
async def test_a_key_whose_requests_have_all_expired_is_dropped() -> None:
    clock = _Clock()
    storage = InMemoryThrottlerStorage(clock=clock)

    await storage.count_request("throttle:203.0.113.5", 60, 5)
    assert len(storage) == 1

    clock.advance(61)
    state = await storage.count_request("throttle:203.0.113.9", 60, 0)

    assert state.count == 1
    assert len(storage) == 1


@pytest.mark.anyio
async def test_a_refused_request_does_not_extend_the_wait_it_reports() -> None:
    clock = _Clock()
    storage = InMemoryThrottlerStorage(clock=clock)

    first = await storage.count_request("k", 60, 1)
    assert (first.count, first.reset_after) == (1, 60)

    clock.advance(20)
    refused = await storage.count_request("k", 60, 1)
    assert (refused.count, refused.reset_after) == (2, 40)

    clock.advance(20)
    still_refused = await storage.count_request("k", 60, 1)
    assert (still_refused.count, still_refused.reset_after) == (2, 20)

    clock.advance(21)
    accepted = await storage.count_request("k", 60, 1)
    assert accepted.count == 1


def test_max_keys_below_one_is_rejected() -> None:
    with pytest.raises(ValueError, match="max_keys"):
        InMemoryThrottlerStorage(max_keys=0)


def test_the_refusal_carries_a_computed_retry_after() -> None:
    clock = _Clock()
    storage = InMemoryThrottlerStorage(clock=clock)

    with TestClient(_throttled_app(ttl=60, limit=1, storage=storage)) as client:
        assert client.get("/").status_code == 200

        clock.advance(15)
        first_refusal = client.get("/")

        clock.advance(30)
        later_refusal = client.get("/")

    assert first_refusal.status_code == 429
    assert first_refusal.headers["Retry-After"] == "45"
    assert later_refusal.status_code == 429
    assert later_refusal.headers["Retry-After"] == "15"
    assert later_refusal.headers["X-RateLimit-Reset"] == "15"


def test_a_successful_response_carries_no_retry_after() -> None:
    with TestClient(_throttled_app(ttl=60, limit=5)) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "Retry-After" not in response.headers


def test_a_spoofed_forwarding_header_from_an_untrusted_peer_is_ignored() -> None:
    """The trusted-proxy list is the security boundary, so the spoof is what is tested.

    An untrusted peer that sends a fresh ``X-Forwarded-For`` on every request would, if
    the header were believed, be counted under a new key each time and never be refused.
    """

    app = _throttled_app(ttl=60, limit=1, trusted_proxies=["192.0.2.10"])

    with TestClient(app, client=("203.0.113.7", 44321)) as client:
        first = client.get("/", headers={"x-forwarded-for": "198.51.100.1"})
        second = client.get("/", headers={"x-forwarded-for": "198.51.100.2"})
        third = client.get("/", headers={"x-forwarded-for": "198.51.100.3"})

    assert first.status_code == 200
    assert second.status_code == 429
    assert third.status_code == 429


def test_a_forwarding_header_from_a_trusted_peer_names_the_caller() -> None:
    app = _throttled_app(ttl=60, limit=1, trusted_proxies=["192.0.2.0/24"])

    with TestClient(app, client=("192.0.2.10", 44321)) as client:
        first = client.get("/", headers={"x-forwarded-for": "198.51.100.1"})
        other = client.get("/", headers={"x-forwarded-for": "198.51.100.2"})
        repeat = client.get("/", headers={"x-forwarded-for": "198.51.100.1"})

    assert first.status_code == 200
    assert other.status_code == 200
    assert repeat.status_code == 429


def test_a_caller_cannot_hide_behind_addresses_prepended_to_the_chain() -> None:
    """Only the entries a trusted proxy appended count, so the chain is read from the right."""

    app = _throttled_app(ttl=60, limit=1, trusted_proxies=["192.0.2.0/24"])

    with TestClient(app, client=("192.0.2.10", 44321)) as client:
        first = client.get("/", headers={"x-forwarded-for": "10.0.0.1, 198.51.100.1"})
        second = client.get("/", headers={"x-forwarded-for": "10.0.0.2, 198.51.100.1"})

    assert first.status_code == 200
    assert second.status_code == 429


def test_trusted_proxies_in_the_chain_are_skipped_over() -> None:
    app = _throttled_app(ttl=60, limit=1, trusted_proxies=["192.0.2.0/24"])

    with TestClient(app, client=("192.0.2.10", 44321)) as client:
        first = client.get("/", headers={"x-forwarded-for": "198.51.100.1, 192.0.2.20"})
        second = client.get("/", headers={"x-forwarded-for": "198.51.100.1, 192.0.2.21"})

    assert first.status_code == 200
    assert second.status_code == 429


def test_an_unparseable_forwarding_entry_falls_back_to_the_peer() -> None:
    """A key must never be built from a value that is not an address the proxy vouched for."""

    app = _throttled_app(ttl=60, limit=1, trusted_proxies=["192.0.2.0/24"])

    with TestClient(app, client=("192.0.2.10", 44321)) as client:
        first = client.get("/", headers={"x-forwarded-for": "not-an-address"})
        second = client.get("/", headers={"x-forwarded-for": "also-not-an-address"})

    assert first.status_code == 200
    assert second.status_code == 429


def test_two_spellings_of_one_forwarded_address_share_a_window() -> None:
    app = _throttled_app(ttl=60, limit=1, trusted_proxies=["192.0.2.0/24"])

    with TestClient(app, client=("192.0.2.10", 44321)) as client:
        first = client.get("/", headers={"x-forwarded-for": "[2001:db8:0:0:0:0:0:1]:9000"})
        second = client.get("/", headers={"x-forwarded-for": "2001:db8::1"})

    assert first.status_code == 200
    assert second.status_code == 429


def test_forwarding_headers_are_ignored_when_no_proxy_is_trusted() -> None:
    app = _throttled_app(ttl=60, limit=1)

    with TestClient(app, client=("192.0.2.10", 44321)) as client:
        first = client.get("/", headers={"x-forwarded-for": "198.51.100.1"})
        second = client.get("/", headers={"x-forwarded-for": "198.51.100.2"})

    assert first.status_code == 200
    assert second.status_code == 429


def test_a_chain_of_nothing_but_trusted_proxies_falls_back_to_the_peer() -> None:
    app = _throttled_app(ttl=60, limit=1, trusted_proxies=["192.0.2.0/24"])

    with TestClient(app, client=("192.0.2.10", 44321)) as client:
        first = client.get("/", headers={"x-forwarded-for": "192.0.2.30, 192.0.2.20"})
        second = client.get("/", headers={"x-forwarded-for": "192.0.2.31, 192.0.2.21"})

    assert first.status_code == 200
    assert second.status_code == 429


def test_a_forwarded_entry_carrying_a_port_names_the_same_caller_without_it() -> None:
    app = _throttled_app(ttl=60, limit=1, trusted_proxies=["192.0.2.0/24"])

    with TestClient(app, client=("192.0.2.10", 44321)) as client:
        first = client.get("/", headers={"x-forwarded-for": "198.51.100.1:5000"})
        second = client.get("/", headers={"x-forwarded-for": "198.51.100.1"})

    assert first.status_code == 200
    assert second.status_code == 429


class _StubContext:
    """The two shapes the resolver has to survive that a served request never takes."""

    def __init__(self, request: object | None) -> None:
        self.request = request


class _ClientlessRequest:
    client = None
    headers: dict[str, str] = {}


def test_a_request_with_nothing_to_key_on_is_counted_under_one_shared_key() -> None:
    resolve = _client_address_key_resolver(())

    assert resolve(cast(Any, _StubContext(None))) == "throttle:unknown"
    assert resolve(cast(Any, _StubContext(_ClientlessRequest()))) == "throttle:unknown"


@pytest.mark.anyio
async def test_a_fresh_key_is_told_the_whole_window_and_never_a_second_more() -> None:
    """A reading whose window crosses a binade boundary must not gain a second.

    A float holds a clock reading to the precision of the binade it sits in, and the
    next binade up is half as fine. A reading less than one window short of a power of
    two therefore cannot hold the reading plus the window to its own precision: the sum
    rounds, and where it rounds up, subtracting the reading back off leaves a fraction
    more than the window, which a ceiling turns into a whole second too many. Measuring
    the age of the oldest request instead cannot do this, because subtracting a reading
    from itself is exactly zero at every magnitude.

    Each reading below sits three units of the lower binade above the point one window
    short of a power of two, which lands inside the crossing region at every magnitude a
    monotonic clock reaches, from a container two minutes old to a host up for a
    fortnight. Every one of them is asserted to lose the round trip first, so this test
    cannot quietly stop covering the case it was written for.
    """

    ttl = 60
    readings = [2.0**k - 30.0 + 3 * math.ulp(2.0 ** (k - 1)) for k in range(8, 21)]
    assert all(math.ceil((reading + ttl) - reading) == ttl + 1 for reading in readings)

    for reading in readings:
        clock = _Clock()
        clock.now = reading
        storage = InMemoryThrottlerStorage(clock=clock)

        state = await storage.count_request("k", ttl, 5)

        assert (state.count, state.reset_after) == (1, ttl)


@pytest.mark.anyio
async def test_no_reading_across_a_boundary_reports_more_than_the_window() -> None:
    """The whole crossing region, not only the readings picked to round the wrong way."""

    ttl = 60
    boundary = 2.0**18
    readings = [boundary - ttl + step * (ttl / 2_000) for step in range(2_000)]
    losing = [r for r in readings if math.ceil((r + ttl) - r) != ttl]
    assert losing, "the sampled region no longer contains a reading that loses the round trip"

    storage = InMemoryThrottlerStorage(clock=_Clock())
    clock = cast(_Clock, storage.clock)
    for index, reading in enumerate(readings):
        clock.now = reading

        assert (await storage.count_request(f"k{index}", ttl, 5)).reset_after == ttl


@pytest.mark.xfail(
    strict=True,
    reason=(
        "The per-route limit is compiled into the policy plan and never read: the guard "
        "counts every route against the application-wide limit and consults the plan "
        "only for the skip flag. Reading it is the one change this test is waiting for, "
        "and the test passes the moment that lands."
    ),
)
def test_a_per_route_rate_limit_is_enforced_below_the_application_limit() -> None:
    """A route that asks for a tighter limit than the application must get it.

    The application allows five requests a minute and the route allows one, so the
    second request to that route is over the route's limit while still inside the
    application's. A route that answers it has had its declared limit ignored, which is
    indistinguishable to the caller from the route never having declared one.
    """

    @Controller("/")
    class AppController:
        @RateLimit(limit=1, window="1m")
        @Get("/")
        def index(self) -> dict[str, str]:
            return {"status": "ok"}

    @Module(imports=[ThrottlerModule.for_root(ttl=60, limit=5)], controllers=[AppController])
    class AppModule:
        pass

    with TestClient(cast(Any, create_app(AppModule))) as client:
        first = client.get("/")
        second = client.get("/")

    assert first.status_code == 200
    assert second.status_code == 429
