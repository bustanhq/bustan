"""The declared request state namespace must admit what the framework already stores."""

from __future__ import annotations

from typing import TYPE_CHECKING

from bustan.addons.context import REQUEST_CONTEXT_ID_ATTR
from bustan.contracts import HttpRequest, HttpRequestState
from bustan.core.ioc.scopes import REQUEST_SCOPE_CACHE_ATTR, REQUEST_SCOPE_CONTROLLER_CACHE_ATTR
from bustan.platform.http.abstractions import StarletteHttpRequest

if TYPE_CHECKING:
    from tests.conftest import RequestFactory

# Everything the framework itself keeps on request state today. The provider and
# controller caches and the context identifier are written through their constants;
# the principal is written by the authenticating guard and the rate limit counters by
# the throttler for the response writer to read back.
FRAMEWORK_STATE_ATTRIBUTES = (
    REQUEST_SCOPE_CACHE_ATTR,
    REQUEST_SCOPE_CONTROLLER_CACHE_ATTR,
    REQUEST_CONTEXT_ID_ATTR,
    "principal",
    "rate_limit_limit",
    "rate_limit_remaining",
    "rate_limit_reset",
    "rate_limit_exceeded",
)


def test_a_live_request_state_satisfies_the_declared_namespace(
    build_request: RequestFactory,
) -> None:
    request = StarletteHttpRequest(build_request())

    assert isinstance(request, HttpRequest)
    assert isinstance(request.state, HttpRequestState)


def test_something_without_open_attribute_access_is_not_a_state_namespace() -> None:
    assert not isinstance(object(), HttpRequestState)


def test_every_attribute_the_framework_stores_round_trips(build_request: RequestFactory) -> None:
    state = StarletteHttpRequest(build_request()).state

    for index, attribute in enumerate(FRAMEWORK_STATE_ATTRIBUTES):
        setattr(state, attribute, index)

    for index, attribute in enumerate(FRAMEWORK_STATE_ATTRIBUTES):
        assert getattr(state, attribute) == index


def test_an_attribute_that_was_never_written_reports_as_absent(
    build_request: RequestFactory,
) -> None:
    state = StarletteHttpRequest(build_request()).state

    assert not hasattr(state, "principal")
    assert getattr(state, "principal", None) is None

    state.principal = None

    assert hasattr(state, "principal")


def test_deleting_an_attribute_makes_the_slot_absent_again(
    build_request: RequestFactory,
) -> None:
    state = StarletteHttpRequest(build_request()).state
    setattr(state, REQUEST_SCOPE_CACHE_ATTR, {})

    delattr(state, REQUEST_SCOPE_CACHE_ATTR)

    assert not hasattr(state, REQUEST_SCOPE_CACHE_ATTR)


def test_state_is_per_request_rather_than_shared(build_request: RequestFactory) -> None:
    first = StarletteHttpRequest(build_request()).state
    second = StarletteHttpRequest(build_request()).state

    first.principal = "ada"

    assert not hasattr(second, "principal")
