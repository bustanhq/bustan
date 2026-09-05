"""The neutral request contract over a raw ASGI connection."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from bustan.adapters.asgi.requests import (
    AsgiHttpRequest,
    ClientDisconnected,
    RequestBodyTooLarge,
    from_asgi_request,
)
from bustan.contracts import (
    Headers,
    HttpClientInfo,
    HttpRequest,
    QueryParams,
    RateLimitDecision,
    RequestState,
    Url,
)

if TYPE_CHECKING:
    from bustan.adapters.asgi.types import Message

    from .conftest import ReceiveFactory, ScopeFactory


async def _empty_receive() -> Message:
    return {"type": "http.request", "body": b"", "more_body": False}


def test_a_request_reports_the_method_and_path_the_scope_carried(
    build_scope: ScopeFactory,
) -> None:
    request = AsgiHttpRequest(build_scope(method="post", path="/users/7"), _empty_receive)

    assert request.method == "POST"
    assert request.path == "/users/7"


def test_every_request_value_is_the_neutral_type_rather_than_a_transport_object(
    build_scope: ScopeFactory,
) -> None:
    scope = build_scope(
        path="/users/7",
        query_string=b"tag=a&tag=b",
        headers=[(b"host", b"example.test:8080"), (b"X-Trace", b"abc")],
    )
    request = AsgiHttpRequest(scope, _empty_receive)

    assert isinstance(request.url, Url)
    assert isinstance(request.headers, Headers)
    assert isinstance(request.query_params, QueryParams)
    assert isinstance(request.state, RequestState)
    assert isinstance(request.client, HttpClientInfo)
    assert isinstance(request, HttpRequest)


def test_the_url_is_built_from_the_host_header_the_request_arrived_with(
    build_scope: ScopeFactory,
) -> None:
    scope = build_scope(
        path="/users/7",
        query_string=b"page=2",
        headers=[(b"host", b"example.test:8080")],
    )

    url = AsgiHttpRequest(scope, _empty_receive).url

    assert url == Url(
        scheme="http", host="example.test", port=8080, path="/users/7", query_string="page=2"
    )
    assert str(url) == "http://example.test:8080/users/7?page=2"


def test_the_url_falls_back_to_the_server_the_scope_named_when_no_host_arrived(
    build_scope: ScopeFactory,
) -> None:
    scope = build_scope(headers=[])

    assert AsgiHttpRequest(scope, _empty_receive).url.host == "testserver"


def test_a_request_with_neither_a_host_header_nor_a_server_reports_no_host(
    build_scope: ScopeFactory,
) -> None:
    scope = build_scope(headers=[])
    del scope["server"]

    assert AsgiHttpRequest(scope, _empty_receive).url.host == ""


def test_headers_are_looked_up_without_regard_to_case_and_keep_repeats(
    build_scope: ScopeFactory,
) -> None:
    scope = build_scope(headers=[(b"X-Tag", b"one"), (b"x-tag", b"two")])

    headers = AsgiHttpRequest(scope, _empty_receive).headers

    assert headers["X-TAG"] == "one, two"
    assert headers.getlist("x-tag") == ["one", "two"]


def test_query_parameters_keep_every_value_of_a_repeated_key(
    build_scope: ScopeFactory,
) -> None:
    scope = build_scope(query_string=b"tag=a&tag=b&page=2")

    query_params = AsgiHttpRequest(scope, _empty_receive).query_params

    assert query_params.getlist("tag") == ["a", "b"]
    assert query_params["page"] == "2"


def test_cookies_are_read_from_every_cookie_header(build_scope: ScopeFactory) -> None:
    scope = build_scope(headers=[(b"cookie", b"session=abc"), (b"cookie", b"theme=dark")])

    assert AsgiHttpRequest(scope, _empty_receive).cookies == {
        "session": "abc",
        "theme": "dark",
    }


def test_a_request_without_a_client_reports_none(build_scope: ScopeFactory) -> None:
    assert AsgiHttpRequest(build_scope(client=None), _empty_receive).client is None


def test_the_router_supplies_the_parameters_captured_from_the_path(
    build_scope: ScopeFactory,
) -> None:
    request = AsgiHttpRequest(build_scope(path="/users/7"), _empty_receive)

    assert request.path_params == {}

    request.set_path_params({"user_id": "7"})

    assert request.path_params == {"user_id": "7"}


def test_state_is_a_view_over_the_scope_rather_than_a_copy_of_it(
    build_scope: ScopeFactory,
) -> None:
    scope = build_scope()
    request = AsgiHttpRequest(scope, _empty_receive)

    request.state.principal = "ada"

    assert scope["state"]["principal"] == "ada"
    assert AsgiHttpRequest(scope, _empty_receive).state.principal == "ada"


def test_the_typed_slots_are_the_same_object_for_every_wrapper_of_one_request(
    build_scope: ScopeFactory,
) -> None:
    scope = build_scope()
    decision = RateLimitDecision(limit=10, remaining=9, reset=60, exceeded=False)

    AsgiHttpRequest(scope, _empty_receive).slots.rate_limit = decision

    assert AsgiHttpRequest(scope, _empty_receive).slots.rate_limit is decision


def test_the_native_request_is_the_wrapper_itself_and_exposes_the_asgi_objects(
    build_scope: ScopeFactory,
) -> None:
    scope = build_scope()
    request = AsgiHttpRequest(scope, _empty_receive)

    assert request.native_request is request
    assert request.scope is scope
    assert request.receive is _empty_receive


def test_the_application_is_whatever_the_server_attached_to_the_scope(
    build_scope: ScopeFactory,
) -> None:
    marker = object()

    assert AsgiHttpRequest(build_scope(app=marker), _empty_receive).app is marker


@pytest.mark.anyio
async def test_a_body_split_across_messages_is_read_whole_and_kept(
    build_scope: ScopeFactory, build_receive: ReceiveFactory
) -> None:
    request = AsgiHttpRequest(build_scope(), build_receive(b"hello body", chunks=3))

    assert await request.body() == b"hello body"
    # A second read must not reach for the stream again; the stream is now exhausted.
    assert await request.body() == b"hello body"


@pytest.mark.anyio
async def test_a_json_body_is_decoded(
    build_scope: ScopeFactory, build_receive: ReceiveFactory
) -> None:
    request = AsgiHttpRequest(build_scope(), build_receive(b'{"name": "Ada"}'))

    assert await request.json() == {"name": "Ada"}


@pytest.mark.anyio
async def test_a_form_body_is_parsed_according_to_its_content_type(
    build_scope: ScopeFactory, build_receive: ReceiveFactory
) -> None:
    scope = build_scope(
        method="POST",
        headers=[(b"content-type", b"application/x-www-form-urlencoded")],
    )
    request = AsgiHttpRequest(scope, build_receive(b"name=Ada&tag=a&tag=b"))

    form = await request.form()

    assert form.get("name") == "Ada"
    assert form.getlist("tag") == ["a", "b"]


@pytest.mark.anyio
async def test_a_body_beyond_the_limit_is_refused_rather_than_buffered(
    build_scope: ScopeFactory, build_receive: ReceiveFactory
) -> None:
    request = AsgiHttpRequest(build_scope(), build_receive(b"x" * 64, chunks=8), max_body_bytes=32)

    with pytest.raises(RequestBodyTooLarge, match="32 byte limit"):
        await request.body()


@pytest.mark.anyio
async def test_a_body_is_unbounded_when_the_adapter_was_built_without_a_limit(
    build_scope: ScopeFactory, build_receive: ReceiveFactory
) -> None:
    request = AsgiHttpRequest(build_scope(), build_receive(b"x" * 64), max_body_bytes=None)

    assert await request.body() == b"x" * 64


@pytest.mark.anyio
async def test_a_client_that_disconnects_mid_body_is_reported_rather_than_truncated(
    build_scope: ScopeFactory,
) -> None:
    messages: list[Message] = [
        {"type": "http.request", "body": b"half", "more_body": True},
        {"type": "http.disconnect"},
    ]

    async def receive() -> Message:
        return messages.pop(0)

    request = AsgiHttpRequest(build_scope(), receive)

    with pytest.raises(ClientDisconnected):
        await request.body()


def test_wrapping_a_request_that_is_already_wrapped_returns_the_same_view(
    build_scope: ScopeFactory,
) -> None:
    request = AsgiHttpRequest(build_scope(), _empty_receive)

    assert from_asgi_request(request) is request


def test_a_scope_and_receive_pair_is_wrapped_into_the_request_contract(
    build_scope: ScopeFactory,
) -> None:
    scope = build_scope(path="/wrapped")

    wrapped = from_asgi_request((scope, _empty_receive))

    assert isinstance(wrapped, AsgiHttpRequest)
    assert wrapped.path == "/wrapped"


def test_anything_else_is_taken_to_be_a_request_contract_already() -> None:
    marker = object()

    assert from_asgi_request(marker) is marker
