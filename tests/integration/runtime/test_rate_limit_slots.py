"""The throttler and the response writer meet on a typed slot, not on loose attributes."""

from __future__ import annotations

from typing import Any, cast

import pytest
from starlette.testclient import TestClient

from bustan import Controller, Get, Module, ThrottlerModule, create_app
from bustan.adapters.starlette import StarletteHttpRequest
from bustan.contracts import RateLimitDecision
from bustan.security.throttler import InMemoryThrottlerStorage, ThrottlerGuard


@Controller("/limited")
class LimitedController:
    @Get("/")
    def index(self) -> dict[str, str]:
        return {"status": "ok"}


@Module(imports=[ThrottlerModule.for_root(ttl=60, limit=5)], controllers=[LimitedController])
class ThrottledModule:
    pass


def test_the_throttler_writes_a_typed_slot_the_response_writer_reads_back() -> None:
    with TestClient(cast(Any, create_app(ThrottledModule))) as client:
        response = client.get("/limited")

    assert response.status_code == 200
    assert response.headers["X-RateLimit-Limit"] == "5"
    assert response.headers["X-RateLimit-Remaining"] == "4"
    assert response.headers["X-RateLimit-Reset"] == "60"


def test_a_request_no_throttler_ran_for_carries_an_empty_slot() -> None:
    @Controller("/open")
    class OpenController:
        @Get("/")
        def index(self) -> dict[str, str]:
            return {"status": "ok"}

    @Module(controllers=[OpenController])
    class AppModule:
        pass

    with TestClient(cast(Any, create_app(AppModule))) as client:
        response = client.get("/open")

    assert response.status_code == 200
    assert "X-RateLimit-Limit" not in response.headers


@pytest.mark.anyio
async def test_the_guard_records_its_decision_on_the_typed_slot(build_request) -> None:
    from bustan.common.types import RouteMetadata
    from bustan.kernel.module.dynamic import ModuleInstanceKey
    from bustan.pipeline.context import RequestContext
    from bustan.runtime.metadata import ControllerRouteDefinition

    request = StarletteHttpRequest(build_request(path="/limited"))
    guard = ThrottlerGuard(
        storage=InMemoryThrottlerStorage(),
        ttl=60,
        limit=1,
        key_resolver=lambda context: "one-key",
    )

    def handler() -> None:
        return None

    context = RequestContext(
        request=request,
        module=ModuleInstanceKey(module=object, instance_id="test"),
        controller_type=object,
        controller=object(),
        route=ControllerRouteDefinition(
            handler_name="handler",
            handler=handler,
            route=RouteMetadata(method="GET", path="/limited", name="handler"),
        ),
        container=cast(Any, object()),
    )

    assert await guard.can_activate(cast(Any, context)) is True

    rate_limit = request.slots.rate_limit
    assert isinstance(rate_limit, RateLimitDecision)
    assert (rate_limit.limit, rate_limit.remaining, rate_limit.exceeded) == (1, 0, False)
    # The counters live on the declared slot, not as free attributes on the namespace.
    assert not hasattr(request.state, "rate_limit_limit")

    assert await guard.can_activate(cast(Any, context)) is False
    assert request.slots.rate_limit is not None
    assert request.slots.rate_limit.exceeded is True
