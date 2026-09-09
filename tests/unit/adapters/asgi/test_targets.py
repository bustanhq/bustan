"""The one parser that reads a request target into the fields of a connection scope."""

from __future__ import annotations

import pytest

from bustan.adapters.asgi.targets import HttpParseError, parse_request_target


def test_a_plain_target_is_read_into_a_path_a_raw_path_and_no_query() -> None:
    parsed = parse_request_target(b"/users/7")

    assert parsed.path == "/users/7"
    assert parsed.raw_path == b"/users/7"
    assert parsed.query_string == b""


def test_the_query_string_begins_at_the_first_question_mark_and_is_left_alone() -> None:
    """What an escape in a query string means is decided by whoever parses it."""

    parsed = parse_request_target(b"/search?q=a%2Bb&next=/x?y")

    assert parsed.path == "/search"
    assert parsed.raw_path == b"/search"
    assert parsed.query_string == b"q=a%2Bb&next=/x?y"


def test_every_segment_is_decoded_so_a_route_matches_what_the_caller_addressed() -> None:
    parsed = parse_request_target(b"/li%74eral/John%20Doe/caf%C3%A9")

    assert parsed.path == "/literal/John Doe/caf\u00e9"
    assert parsed.raw_path == b"/li%74eral/John%20Doe/caf%C3%A9"


def test_an_encoded_separator_stays_inside_the_segment_it_was_written_in() -> None:
    """Decoding it into the path would move the request to a route nobody addressed."""

    parsed = parse_request_target(b"/users/a%2Fb")

    assert parsed.path == "/users/a%2Fb"
    assert parsed.raw_path == b"/users/a%2Fb"


def test_a_lower_case_encoded_separator_is_kept_the_same_way() -> None:
    assert parse_request_target(b"/users/a%2fb").path == "/users/a%2Fb"


def test_a_percent_that_begins_no_escape_stays_the_character_it_is() -> None:
    assert parse_request_target(b"/users/bad%zz").path == "/users/bad%zz"
    assert parse_request_target(b"/users/%").path == "/users/%"
    assert parse_request_target(b"/users/%2").path == "/users/%2"


def test_an_encoded_dot_segment_is_a_name_rather_than_a_navigation() -> None:
    """Neither server this framework runs on collapses one, so neither does this."""

    assert parse_request_target(b"/users/%2E%2E").path == "/users/.."
    assert parse_request_target(b"/users/../7").path == "/users/../7"


def test_a_trailing_slash_survives_as_the_empty_segment_it_is() -> None:
    assert parse_request_target(b"/users/").path == "/users/"
    assert parse_request_target(b"/").path == "/"


def test_a_target_carrying_a_byte_outside_ascii_is_refused_with_the_status_that_answers_it() -> (
    None
):
    with pytest.raises(HttpParseError) as refusal:
        parse_request_target("/users/caf\u00e9".encode("latin-1"))

    assert refusal.value.status == 400
    assert refusal.value.reason == "Non-ASCII byte in the request target"


def test_a_byte_outside_ascii_in_the_query_string_is_refused_too() -> None:
    with pytest.raises(HttpParseError):
        parse_request_target("/users?q=caf\u00e9".encode("latin-1"))


def test_a_segment_whose_escapes_are_not_utf_8_is_refused_rather_than_guessed_at() -> None:
    """A path assembled out of replacement characters is a path nobody addressed."""

    with pytest.raises(HttpParseError) as refusal:
        parse_request_target(b"/users/%FF")

    assert refusal.value.status == 400
    assert refusal.value.reason == "Undecodable percent-encoding in the request target"


def test_a_truncated_multi_byte_escape_is_refused_as_well() -> None:
    with pytest.raises(HttpParseError):
        parse_request_target(b"/users/%E2%82")
