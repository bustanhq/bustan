"""Unit tests for the correlation and trace context one request carries."""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Callable, Iterator, Mapping
from types import CodeType
from typing import cast

import pytest

from bustan.contracts import Headers
from bustan.observability.correlation import (
    MAX_CORRELATION_ID_LENGTH,
    bind_correlation,
    correlation_from_headers,
    current_correlation,
    current_correlation_id,
    parse_traceparent,
    reset_correlation,
    trace_id_sampled,
)

_CALLER_TRACEPARENT = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
_LONG_ID = re.compile(r"\A[0-9a-f]{32}\Z")
_SPAN_ID = re.compile(r"\A[0-9a-f]{16}\Z")

type SentHeaders = Callable[[dict[str, str]], Mapping[str, str]]


def _as_headers(sent: dict[str, str]) -> Mapping[str, str]:
    return Headers(sent.items())


@pytest.fixture(params=[dict, _as_headers], ids=["dict", "Headers"])
def sent(request: pytest.FixtureRequest) -> SentHeaders:
    """Send headers as a plain dict, and again as the Headers both adapters hand over."""

    return cast(SentHeaders, request.param)


def test_a_request_without_a_correlation_id_is_given_one(sent: SentHeaders) -> None:
    correlation = correlation_from_headers(sent({}))

    assert correlation.correlation_id
    assert len(correlation.trace_id) == 32
    assert len(correlation.span_id) == 16
    assert correlation.parent_span_id is None
    assert correlation.parent_sampled is None


def test_a_correlation_id_the_caller_supplied_is_honoured(sent: SentHeaders) -> None:
    correlation = correlation_from_headers(sent({"X-Correlation-Id": "req-42"}))

    assert correlation.correlation_id == "req-42"


def test_the_request_id_header_is_honoured_when_no_correlation_id_was_sent(
    sent: SentHeaders,
) -> None:
    correlation = correlation_from_headers(sent({"x-request-id": "req-7"}))

    assert correlation.correlation_id == "req-7"


def test_the_correlation_id_header_is_preferred_to_the_request_id(sent: SentHeaders) -> None:
    correlation = correlation_from_headers(
        sent({"x-request-id": "req-7", "x-correlation-id": "req-42"})
    )

    assert correlation.correlation_id == "req-42"


def test_a_correlation_id_that_could_forge_a_record_is_replaced_not_repaired(
    sent: SentHeaders,
) -> None:
    forged = "req-1\n[2026-01-01T00:00:00.000Z] [ERROR] [Auth] admin login failed"

    correlation = correlation_from_headers(sent({"x-correlation-id": forged}))

    assert correlation.correlation_id != forged
    assert "\n" not in correlation.correlation_id


def test_an_oversized_correlation_id_is_replaced(sent: SentHeaders) -> None:
    oversized = "a" * (MAX_CORRELATION_ID_LENGTH + 1)

    correlation = correlation_from_headers(sent({"x-correlation-id": oversized}))

    assert correlation.correlation_id != oversized


def test_a_refused_correlation_id_gives_way_to_the_request_id(sent: SentHeaders) -> None:
    oversized = "a" * (MAX_CORRELATION_ID_LENGTH + 1)

    correlation = correlation_from_headers(
        sent({"x-correlation-id": oversized, "x-request-id": "req-7"})
    )

    assert correlation.correlation_id == "req-7"


def test_a_header_sent_twice_is_refused_rather_than_either_copy_chosen() -> None:
    correlation = correlation_from_headers(
        Headers(
            [
                ("x-correlation-id", "req-1"),
                ("X-Correlation-Id", "req-2"),
                ("traceparent", _CALLER_TRACEPARENT),
                ("traceparent", _CALLER_TRACEPARENT),
            ]
        )
    )

    assert correlation.correlation_id not in {"req-1", "req-2"}
    assert correlation.parent_span_id is None


@pytest.mark.parametrize(
    ("correlation_id_name", "request_id_name", "traceparent_name"),
    [
        ("x-correlation-id", "x-request-id", "traceparent"),
        ("X-Correlation-Id", "X-Request-Id", "Traceparent"),
        ("X-CORRELATION-ID", "X-REQUEST-ID", "TRACEPARENT"),
        ("x-cORRELATION-iD", "x-rEQUEST-iD", "tRACEPARENT"),
    ],
)
def test_a_dict_of_headers_is_read_whatever_case_its_names_are_written_in(
    correlation_id_name: str, request_id_name: str, traceparent_name: str
) -> None:
    by_correlation_id = correlation_from_headers({correlation_id_name: "req-42"})
    by_request_id = correlation_from_headers({request_id_name: "req-7"})
    joined = correlation_from_headers({traceparent_name: _CALLER_TRACEPARENT})

    assert by_correlation_id.correlation_id == "req-42"
    assert by_request_id.correlation_id == "req-7"
    assert joined.trace_id == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert joined.parent_span_id == "00f067aa0ba902b7"


class _UnscannableHeaders(Headers):
    """Headers that fail the test the moment anything iterates over their names."""

    __slots__ = ()

    def __iter__(self) -> Iterator[str]:
        raise AssertionError("the headers were scanned instead of read by name")


def test_headers_that_fold_case_are_read_by_name_and_never_scanned() -> None:
    correlation = correlation_from_headers(
        _UnscannableHeaders([("Host", "example.test"), ("X-Request-Id", "req-7")])
    )

    assert correlation.correlation_id == "req-7"
    assert correlation.parent_span_id is None


def test_a_traceparent_joins_the_request_to_the_callers_trace(sent: SentHeaders) -> None:
    correlation = correlation_from_headers(sent({"traceparent": _CALLER_TRACEPARENT}))

    assert correlation.trace_id == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert correlation.parent_span_id == "00f067aa0ba902b7"
    assert correlation.parent_sampled is True
    # The span this process runs is a new span inside the caller's trace, never the
    # caller's own span reused under a second name.
    assert correlation.span_id != "00f067aa0ba902b7"


def test_an_unsampled_traceparent_carries_the_callers_decision_forward(
    sent: SentHeaders,
) -> None:
    correlation = correlation_from_headers(
        sent({"traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-00"})
    )

    assert correlation.parent_sampled is False


def test_a_malformed_traceparent_starts_a_new_trace_rather_than_failing(
    sent: SentHeaders,
) -> None:
    for header in (
        "not-a-traceparent",
        "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7",
        "ff-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
        f"00-{'0' * 32}-00f067aa0ba902b7-01",
        f"00-4bf92f3577b34da6a3ce929d0e0e4736-{'0' * 16}-01",
        "00-4BF92F3577B34DA6A3CE929D0E0E473-00f067aa0ba902b7-01",
    ):
        assert parse_traceparent(header) is None, header
        assert correlation_from_headers(sent({"traceparent": header})).parent_span_id is None


def test_a_traceparent_is_read_whatever_case_it_was_written_in() -> None:
    parsed = parse_traceparent(_CALLER_TRACEPARENT.upper())

    assert parsed is not None
    assert parsed.trace_id == "4bf92f3577b34da6a3ce929d0e0e4736"


def test_the_outgoing_traceparent_names_this_processs_span(sent: SentHeaders) -> None:
    correlation = correlation_from_headers(sent({"traceparent": _CALLER_TRACEPARENT}))

    assert correlation.traceparent() == (
        f"00-4bf92f3577b34da6a3ce929d0e0e4736-{correlation.span_id}-01"
    )


def _random_source_reads(action: Callable[[], object]) -> int:
    """Return how many times *action* calls ``os.urandom``.

    The calls are watched rather than ``os.urandom`` replaced, because the standard
    library's token functions reach it through a reference ``random`` took when it was
    imported, which replacing the attribute on ``os`` would never touch.
    """

    tool = sys.monitoring.PROFILER_ID
    call = sys.monitoring.events.CALL
    reads: list[object] = []

    def watch(code: CodeType, offset: int, called: object, argument: object) -> None:
        if called is os.urandom:
            reads.append(called)

    sys.monitoring.use_tool_id(tool, "random source reads")
    sys.monitoring.register_callback(tool, call, watch)
    sys.monitoring.set_events(tool, call)
    try:
        action()
    finally:
        sys.monitoring.set_events(tool, sys.monitoring.events.NO_EVENTS)
        sys.monitoring.register_callback(tool, call, None)
        sys.monitoring.free_tool_id(tool)
    return len(reads)


def test_a_request_that_sends_none_of_the_headers_reads_the_random_source_once(
    sent: SentHeaders,
) -> None:
    headers = sent({"host": "example.test", "accept": "*/*"})

    assert _random_source_reads(lambda: correlation_from_headers(headers)) == 1


def test_every_request_is_given_full_length_ids_no_other_request_shares(
    sent: SentHeaders,
) -> None:
    correlations = [correlation_from_headers(sent({})) for _ in range(1000)]
    long_ids = [
        value
        for correlation in correlations
        for value in (correlation.correlation_id, correlation.trace_id)
    ]
    span_ids = [correlation.span_id for correlation in correlations]

    assert all(_LONG_ID.match(value) for value in long_ids)
    assert all(_SPAN_ID.match(value) for value in span_ids)
    assert len(set(long_ids)) == len(long_ids)
    assert len(set(span_ids)) == len(span_ids)
    # The ids of one request come out of a single read of the random source, so an id
    # cut from bytes another id had already taken would turn up inside that other id.
    assert not any(
        correlation.span_id in correlation.correlation_id
        or correlation.span_id in correlation.trace_id
        for correlation in correlations
    )


def test_nothing_is_bound_until_a_request_binds_it() -> None:
    assert current_correlation() is None
    assert current_correlation_id() is None


def test_a_bound_correlation_is_visible_until_it_is_reset() -> None:
    correlation = correlation_from_headers({"x-correlation-id": "req-42"})

    token = bind_correlation(correlation)
    try:
        assert current_correlation_id() == "req-42"
    finally:
        reset_correlation(token)

    assert current_correlation_id() is None


def test_head_sampling_keeps_everything_at_one_and_nothing_at_zero() -> None:
    trace_id = "4bf92f3577b34da6a3ce929d0e0e4736"

    assert trace_id_sampled(trace_id, 1.0) is True
    assert trace_id_sampled(trace_id, 0.0) is False


def test_head_sampling_is_a_function_of_the_trace_id_alone() -> None:
    sampled_at_half = [
        trace_id_sampled(f"{index:032x}", 0.5) for index in range(1 << 63, (1 << 63) + 4)
    ]

    # Same input, same answer, every time and in every process: a trace sampled by the
    # service that started it is sampled by the next service that sees it.
    assert sampled_at_half == [
        trace_id_sampled(f"{index:032x}", 0.5) for index in range(1 << 63, (1 << 63) + 4)
    ]
    assert trace_id_sampled(f"{0:032x}", 0.5) is True
    assert trace_id_sampled(f"{(1 << 64) - 1:032x}", 0.5) is False
