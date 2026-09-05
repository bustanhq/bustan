"""The Starlette request wrapper must hand the framework neutral values only."""

from __future__ import annotations

from typing import TYPE_CHECKING

import anyio
import pytest
from starlette.datastructures import URL as StarletteURL
from starlette.datastructures import QueryParams as StarletteQueryParams
from starlette.datastructures import State as StarletteState
from starlette.requests import Request

from bustan.adapters.starlette import StarletteHttpRequest, from_starlette_request
from bustan.contracts import (
    Headers,
    HttpClientInfo,
    HttpRequest,
    QueryParams,
    RequestSlots,
    RequestState,
    Url,
)

if TYPE_CHECKING:
    from tests.conftest import RequestFactory


def test_the_wrapper_exposes_stable_request_fields(build_request: RequestFactory) -> None:
    request = build_request(method="POST", path="/users?active=true", raw_body=b'{"name":"Ada"}')
    wrapped = StarletteHttpRequest(request)

    assert wrapped.method == "POST"
    assert wrapped.path == "/users"
    assert wrapped.headers["host"] == "testserver"
    assert wrapped.query_params["active"] == "true"
    assert anyio.run(wrapped.body) == b'{"name":"Ada"}'


def test_no_starlette_object_is_reachable_through_the_request_contract(
    build_request: RequestFactory,
) -> None:
    request: HttpRequest = StarletteHttpRequest(
        build_request(path="/users?active=true&active=false", cookies={"session": "abc"})
    )

    assert isinstance(request.url, Url)
    assert not isinstance(request.url, StarletteURL)
    assert isinstance(request.query_params, QueryParams)
    assert not isinstance(request.query_params, StarletteQueryParams)
    assert isinstance(request.state, RequestState)
    assert not isinstance(request.state, StarletteState)
    assert isinstance(request.headers, Headers)
    assert type(request.path_params) is dict
    assert type(request.cookies) is dict
    assert isinstance(request.slots, RequestSlots)
    assert isinstance(request.client, HttpClientInfo)


def test_the_url_reports_the_parts_the_request_arrived_with(
    build_request: RequestFactory,
) -> None:
    url = StarletteHttpRequest(build_request(path="/users?active=true")).url

    assert url.scheme == "http"
    assert url.host == "testserver"
    assert url.path == "/users"
    assert url.query_string == "active=true"


def test_repeated_query_parameters_keep_every_value(build_request: RequestFactory) -> None:
    query_params = StarletteHttpRequest(build_request(path="/users?tag=a&tag=b")).query_params

    assert query_params.getlist("tag") == ["a", "b"]
    assert query_params["tag"] == "b"


def test_state_written_through_one_wrapper_is_read_through_the_next(
    build_request: RequestFactory,
) -> None:
    request = build_request()

    StarletteHttpRequest(request).state.principal = "ada"

    assert StarletteHttpRequest(request).state.principal == "ada"
    # The Starlette request keeps the same state, because it is the same storage.
    assert request.state.principal == "ada"


def test_the_typed_slots_are_the_same_object_for_the_same_request(
    build_request: RequestFactory,
) -> None:
    request = build_request()

    first = StarletteHttpRequest(request).slots
    second = StarletteHttpRequest(request).slots

    assert first is second
    assert first.rate_limit is None


def test_a_request_with_no_client_reports_none(build_request: RequestFactory) -> None:
    request = build_request()
    del request.scope["client"]

    assert StarletteHttpRequest(request).client is None


def test_wrapping_an_already_wrapped_request_returns_it_unchanged(
    build_request: RequestFactory,
) -> None:
    wrapped = StarletteHttpRequest(build_request())

    assert from_starlette_request(wrapped) is wrapped


def test_wrapping_a_starlette_request_produces_the_neutral_contract(
    build_request: RequestFactory,
) -> None:
    request = build_request()

    converted = from_starlette_request(request)

    assert isinstance(converted, StarletteHttpRequest)
    assert converted.native_request is request


def test_something_that_is_already_neutral_is_passed_through() -> None:
    sentinel = object()

    assert from_starlette_request(sentinel) is sentinel


def test_the_wrapper_decodes_a_json_body(build_request: RequestFactory) -> None:
    request = build_request(method="POST", path="/users", json_body={"name": "Ada"})

    assert anyio.run(StarletteHttpRequest(request).json) == {"name": "Ada"}


@pytest.mark.parametrize("attribute", ["app", "native_request"])
def test_the_declared_escape_hatches_still_reach_the_transport(
    build_request: RequestFactory, build_app, attribute: str
) -> None:
    app = build_app()
    wrapped = StarletteHttpRequest(build_request(app=app))

    assert getattr(wrapped, attribute) is not None
    assert isinstance(wrapped.native_request, Request)
