"""The identifiers the public context helpers hand out.

The one worth stating twice is the request identifier: it names one request, so it has
to be unique to that request and the same every time it is asked for. Deriving it from
``id(request)`` satisfied only the second. CPython reuses the address of an object it
has collected, so two requests that never overlap are handed the same value and
anything keyed on it attributes one caller's activity to the next.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.requests import Request

from bustan.addons.context import (
    ContextId,
    application_context_id,
    durable_context_id,
    request_context_id,
)

if TYPE_CHECKING:
    from bustan.contracts import HttpRequest
    from tests.conftest import HttpRequestFactory

REQUESTS = 200


class AppModule:
    """A stand-in module key for the application identifier under test."""


class TenantContext:
    """A stand-in durable provider for the durable identifier under test."""

    @classmethod
    def get_durable_context_key(cls, request: HttpRequest | None) -> str:
        return "tenant-a"


def test_sequential_requests_are_never_handed_the_same_identifier(
    build_http_request: HttpRequestFactory,
) -> None:
    # Each request is released before the next is built, which is the condition under
    # which addresses are reused: the audit measured 200 sequential requests producing
    # 37 distinct values, one of them serving five different callers.
    seen: list[str] = []
    for index in range(REQUESTS):
        request = build_http_request(path=f"/items/{index}")
        seen.append(request_context_id(request).value)
        del request

    assert len(set(seen)) == REQUESTS


def test_one_request_keeps_the_identifier_it_was_first_given(
    build_http_request: HttpRequestFactory,
) -> None:
    request = build_http_request(path="/items")

    first = request_context_id(request)

    assert request_context_id(request) == first
    assert request_context_id(request).value == first.value


def test_two_readings_of_one_request_share_its_identifier(
    build_http_request: HttpRequestFactory,
) -> None:
    # A request read twice is one request. The identifier is kept on the state the ASGI
    # scope carries, so the second reading answers what the first minted rather than
    # naming the same caller twice over.
    from bustan.adapters.starlette.requests import StarletteHttpRequest

    request = build_http_request(path="/items")
    native = request.native_request
    assert isinstance(native, Request)
    same_request_again = StarletteHttpRequest(Request(native.scope, native.receive))

    assert request_context_id(same_request_again) == request_context_id(request)


def test_no_request_is_named_as_no_request() -> None:
    assert request_context_id(None) == ContextId(scope="request", value="none")


def test_the_application_and_durable_identifiers_name_what_they_are_derived_from(
    build_http_request: HttpRequestFactory,
) -> None:
    request = build_http_request(path="/items")

    application = application_context_id(AppModule)
    durable = durable_context_id(TenantContext, request)

    assert application == ContextId(scope="application", value="AppModule")
    assert durable == ContextId(scope="durable", value="TenantContext:'tenant-a'")
    assert len({application, durable, request_context_id(request)}) == 3
