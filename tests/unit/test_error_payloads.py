"""Unit tests for structured error payload helpers."""

from __future__ import annotations

from bustan.core.errors import BadRequestException, ParameterBindingError


def test_parameter_binding_error_to_payload_includes_optional_fields_when_present() -> None:
    error = ParameterBindingError(
        "invalid binding",
        field="user_id",
        source="path",
        reason="integer expected",
    )

    assert error.to_payload() == {
        "detail": "invalid binding",
        "field": "user_id",
        "source": "path",
        "reason": "integer expected",
    }


def test_bad_request_exception_to_payload_omits_missing_optional_fields() -> None:
    error = BadRequestException("invalid request")

    assert error.to_payload() == {"detail": "invalid request"}
