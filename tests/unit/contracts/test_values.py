"""Neutral URL and query parameter values behave the same without a server present."""

from __future__ import annotations

from bustan.contracts import HttpQueryParams, HttpUrl, QueryParams, Url


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
