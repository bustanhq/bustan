"""Neutral request values behave the same without a server present."""

from __future__ import annotations

import pytest

from bustan.contracts import (
    Headers,
    HttpQueryParams,
    HttpUrl,
    QueryParams,
    RequestState,
    Url,
)


def test_url_reports_only_what_arrived() -> None:
    url = Url(scheme="https", host="example.test", path="/users", query_string="active=true")

    assert url.path == "/users"
    assert url.port is None
    assert url.netloc == "example.test"
    assert str(url) == "https://example.test/users?active=true"


def test_url_keeps_an_explicit_port_in_the_authority() -> None:
    url = Url(scheme="http", host="example.test", port=8080, path="/", fragment="top")

    assert url.netloc == "example.test:8080"
    assert str(url) == "http://example.test:8080/#top"


def test_url_satisfies_the_request_url_contract() -> None:
    assert isinstance(Url(path="/health"), HttpUrl)


def test_query_params_keep_every_repeated_value_in_order() -> None:
    params = QueryParams.from_query_string("?tag=a&tag=b&page=2")

    assert params.getlist("tag") == ["a", "b"]
    assert params.keys() == ("tag", "page")
    assert params.multi_items() == (("tag", "a"), ("tag", "b"), ("page", "2"))
    assert len(params) == 2


def test_subscripting_query_params_returns_the_last_value_for_a_key() -> None:
    params = QueryParams([("tag", "a"), ("tag", "b")])

    assert params["tag"] == "b"
    assert params.get("tag") == "b"
    assert "tag" in params


def test_absent_query_parameters_are_reported_rather_than_invented() -> None:
    params = QueryParams.from_query_string("tag=a")

    assert params.getlist("missing") == []
    assert params.get("missing") is None
    assert params.get("missing", "fallback") == "fallback"
    assert "missing" not in params

    try:
        params["missing"]
    except KeyError:
        pass
    else:  # pragma: no cover - only reached if the contract regresses
        raise AssertionError("expected a KeyError for an absent key")


def test_a_blank_value_is_kept_rather_than_dropped() -> None:
    params = QueryParams.from_query_string("tag=")

    assert params.getlist("tag") == [""]


def test_query_params_satisfy_the_request_query_contract() -> None:
    assert isinstance(QueryParams(), HttpQueryParams)


def test_query_params_compare_and_hash_by_their_contents() -> None:
    first = QueryParams([("tag", "a"), ("tag", "b")])
    second = QueryParams.from_query_string("tag=a&tag=b")

    assert first == second
    assert hash(first) == hash(second)
    assert first != QueryParams([("tag", "b"), ("tag", "a")])
    assert first != object()
    assert repr(first) == "QueryParams([('tag', 'a'), ('tag', 'b')])"


def test_mutating_the_list_a_query_returns_does_not_change_the_parameters() -> None:
    params = QueryParams([("tag", "a")])

    params.getlist("tag").append("b")

    assert params.getlist("tag") == ["a"]


def test_query_params_iterate_over_their_keys() -> None:
    assert list(QueryParams([("tag", "a"), ("page", "2"), ("tag", "b")])) == ["tag", "page"]


def test_a_url_with_no_authority_renders_as_the_path_alone() -> None:
    assert str(Url(path="/health")) == "/health"
    assert str(Url(path="/health", query_string="verbose=1")) == "/health?verbose=1"


def test_neutral_values_hold_plain_data_and_nothing_from_a_server_library() -> None:
    url = Url(scheme="https", host="example.test", port=443, path="/users", query_string="tag=a")
    params = QueryParams.from_query_string(url.query_string)

    assert all(
        type(getattr(url, field_name)) in {str, int, type(None)}
        for field_name in url.__dataclass_fields__
    )
    assert all(
        type(key) is str and all(type(value) is str for value in params.getlist(key))
        for key in params
    )


def test_headers_are_looked_up_without_regard_to_case() -> None:
    headers = Headers([("Host", "testserver"), ("Content-Type", "application/json")])

    assert headers["host"] == "testserver"
    assert headers["CONTENT-TYPE"] == "application/json"
    assert "Host" in headers
    assert "missing" not in headers
    assert 42 not in headers


def test_a_repeated_header_keeps_every_value_and_joins_them_on_lookup() -> None:
    headers = Headers([("Accept", "text/html"), ("accept", "application/json")])

    assert headers.getlist("accept") == ["text/html", "application/json"]
    assert headers["accept"] == "text/html, application/json"
    assert headers.getlist("missing") == []


def test_headers_iterate_in_the_order_and_spelling_they_arrived() -> None:
    headers = Headers([("Host", "a"), ("X-Trace", "b"), ("host", "c")])

    assert list(headers) == ["Host", "X-Trace"]
    assert len(headers) == 2


def test_headers_compare_and_hash_by_their_folded_contents() -> None:
    first = Headers([("Host", "a")])
    second = Headers([("host", "a")])

    assert first == second
    assert hash(first) == hash(second)
    assert first != Headers([("Host", "b")])
    assert first.__eq__(object()) is NotImplemented
    assert repr(first).startswith("Headers(")


def test_request_state_reads_writes_and_deletes_attributes() -> None:
    state = RequestState()

    with pytest.raises(AttributeError):
        _ = state.principal

    state.principal = "ada"
    assert state.principal == "ada"
    assert repr(state) == "RequestState(['principal'])"

    del state.principal
    assert not hasattr(state, "principal")

    with pytest.raises(AttributeError):
        del state.principal


def test_request_state_shares_the_mapping_it_was_given() -> None:
    backing: dict[str, object] = {}
    state = RequestState(backing)

    state.principal = "ada"

    assert backing == {"principal": "ada"}
    assert RequestState(backing).principal == "ada"
