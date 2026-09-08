"""Unit tests for the correlation and trace context one request carries."""

from __future__ import annotations

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


def test_a_request_without_a_correlation_id_is_given_one() -> None:
    correlation = correlation_from_headers({})

    assert correlation.correlation_id
    assert len(correlation.trace_id) == 32
    assert len(correlation.span_id) == 16
    assert correlation.parent_span_id is None
    assert correlation.parent_sampled is None


def test_a_correlation_id_the_caller_supplied_is_honoured() -> None:
    correlation = correlation_from_headers({"X-Correlation-Id": "req-42"})

    assert correlation.correlation_id == "req-42"


def test_the_request_id_header_is_honoured_when_no_correlation_id_was_sent() -> None:
    correlation = correlation_from_headers({"x-request-id": "req-7"})

    assert correlation.correlation_id == "req-7"


def test_a_correlation_id_that_could_forge_a_record_is_replaced_not_repaired() -> None:
    forged = "req-1\n[2026-01-01T00:00:00.000Z] [ERROR] [Auth] admin login failed"

    correlation = correlation_from_headers({"x-correlation-id": forged})

    assert correlation.correlation_id != forged
    assert "\n" not in correlation.correlation_id


def test_an_oversized_correlation_id_is_replaced() -> None:
    oversized = "a" * (MAX_CORRELATION_ID_LENGTH + 1)

    correlation = correlation_from_headers({"x-correlation-id": oversized})

    assert correlation.correlation_id != oversized


def test_a_traceparent_joins_the_request_to_the_callers_trace() -> None:
    correlation = correlation_from_headers({"traceparent": _CALLER_TRACEPARENT})

    assert correlation.trace_id == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert correlation.parent_span_id == "00f067aa0ba902b7"
    assert correlation.parent_sampled is True
    # The span this process runs is a new span inside the caller's trace, never the
    # caller's own span reused under a second name.
    assert correlation.span_id != "00f067aa0ba902b7"


def test_an_unsampled_traceparent_carries_the_callers_decision_forward() -> None:
    correlation = correlation_from_headers(
        {"traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-00"}
    )

    assert correlation.parent_sampled is False


def test_a_malformed_traceparent_starts_a_new_trace_rather_than_failing() -> None:
    for header in (
        "not-a-traceparent",
        "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7",
        "ff-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
        f"00-{'0' * 32}-00f067aa0ba902b7-01",
        f"00-4bf92f3577b34da6a3ce929d0e0e4736-{'0' * 16}-01",
        "00-4BF92F3577B34DA6A3CE929D0E0E473-00f067aa0ba902b7-01",
    ):
        assert parse_traceparent(header) is None, header
        assert correlation_from_headers({"traceparent": header}).parent_span_id is None


def test_a_traceparent_is_read_whatever_case_it_was_written_in() -> None:
    parsed = parse_traceparent(_CALLER_TRACEPARENT.upper())

    assert parsed is not None
    assert parsed.trace_id == "4bf92f3577b34da6a3ce929d0e0e4736"


def test_the_outgoing_traceparent_names_this_processs_span() -> None:
    correlation = correlation_from_headers({"traceparent": _CALLER_TRACEPARENT})

    assert correlation.traceparent() == (
        f"00-4bf92f3577b34da6a3ce929d0e0e4736-{correlation.span_id}-01"
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
