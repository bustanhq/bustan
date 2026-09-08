"""Unit tests for the status exception hierarchy applications raise.

The status, the problem type and the code a class carries are a published contract:
a client that branches on a code, or a runbook that greps for one, breaks the day any
of them changes. They are asserted here as literals, one row per status, so changing
one is a deliberate edit to this table rather than a side effect of editing a class.
"""

from __future__ import annotations

import pytest

from bustan.kernel.errors import (
    AuthenticationRequiredError,
    BadGatewayException,
    BadRequestException,
    BustanError,
    ConflictException,
    ContentTooLargeException,
    ForbiddenException,
    GatewayTimeoutException,
    GuardRejectedError,
    HttpException,
    InternalServerErrorException,
    MethodNotAllowedException,
    NotFoundException,
    NotImplementedException,
    ServiceUnavailableException,
    TooManyRequestsException,
    UnauthorizedException,
    UnprocessableEntityException,
    UnsupportedMediaTypeException,
)

# One row per status the hierarchy covers: the class, and the three published values it
# stands for.
STATUS_CONTRACT: tuple[tuple[type[HttpException], int, str, str], ...] = (
    (BadRequestException, 400, "https://bustan.dev/problems/bad-request", "bad-request"),
    (UnauthorizedException, 401, "https://bustan.dev/problems/unauthorized", "unauthorized"),
    (ForbiddenException, 403, "https://bustan.dev/problems/forbidden", "forbidden"),
    (NotFoundException, 404, "https://bustan.dev/problems/not-found", "not-found"),
    (
        MethodNotAllowedException,
        405,
        "https://bustan.dev/problems/method-not-allowed",
        "method-not-allowed",
    ),
    (ConflictException, 409, "https://bustan.dev/problems/conflict", "conflict"),
    (
        ContentTooLargeException,
        413,
        "https://bustan.dev/problems/content-too-large",
        "content-too-large",
    ),
    (
        UnsupportedMediaTypeException,
        415,
        "https://bustan.dev/problems/unsupported-media-type",
        "unsupported-media-type",
    ),
    (
        UnprocessableEntityException,
        422,
        "https://bustan.dev/problems/unprocessable-entity",
        "unprocessable-entity",
    ),
    (
        TooManyRequestsException,
        429,
        "https://bustan.dev/problems/too-many-requests",
        "too-many-requests",
    ),
    (
        InternalServerErrorException,
        500,
        "https://bustan.dev/problems/internal-server-error",
        "internal-server-error",
    ),
    (
        NotImplementedException,
        501,
        "https://bustan.dev/problems/not-implemented",
        "not-implemented",
    ),
    (BadGatewayException, 502, "https://bustan.dev/problems/bad-gateway", "bad-gateway"),
    (
        ServiceUnavailableException,
        503,
        "https://bustan.dev/problems/service-unavailable",
        "service-unavailable",
    ),
    (
        GatewayTimeoutException,
        504,
        "https://bustan.dev/problems/gateway-timeout",
        "gateway-timeout",
    ),
)


@pytest.mark.parametrize(("exception_type", "status", "problem_type", "code"), STATUS_CONTRACT)
def test_each_status_names_its_own_status_type_and_code(
    exception_type: type[HttpException],
    status: int,
    problem_type: str,
    code: str,
) -> None:
    assert exception_type.status_code == status
    assert exception_type.problem_type == problem_type
    assert exception_type.code == code
    assert issubclass(exception_type, HttpException)
    assert issubclass(exception_type, BustanError)


def test_every_status_in_the_hierarchy_is_named_once_and_reads_as_one_family() -> None:
    statuses = [status for _type, status, *_rest in STATUS_CONTRACT]
    types = [problem_type for *_head, problem_type, _code in STATUS_CONTRACT]
    codes = [code for *_head, code in STATUS_CONTRACT]

    assert len(set(statuses)) == len(statuses)
    assert len(set(types)) == len(types)
    assert len(set(codes)) == len(codes)
    # The code is the tail of the type, so the two cannot come to mean different things.
    assert types == [f"https://bustan.dev/problems/{code}" for code in codes]


def test_a_status_exception_carries_the_message_it_was_given() -> None:
    error = NotFoundException("No account with that identifier")

    assert error.detail == "No account with that identifier"
    assert str(error) == "No account with that identifier"


def test_a_status_exception_left_without_a_message_falls_back_to_its_reason() -> None:
    error = ConflictException()

    assert error.detail == "Conflict"
    assert str(error) == "Conflict"


def test_a_401_carries_a_challenge_so_a_client_knows_how_to_authenticate() -> None:
    assert UnauthorizedException().headers == {"WWW-Authenticate": "Bearer"}


def test_an_application_may_state_the_scheme_it_really_uses() -> None:
    error = UnauthorizedException(headers={"WWW-Authenticate": 'Basic realm="reports"'})

    assert error.headers == {"WWW-Authenticate": 'Basic realm="reports"'}


def test_headers_given_to_a_status_that_declares_none_are_kept() -> None:
    error = ServiceUnavailableException("Draining", headers={"Retry-After": "30"})

    assert error.headers == {"Retry-After": "30"}
    assert ServiceUnavailableException().headers == {}


def test_the_validation_error_joins_the_hierarchy_and_keeps_its_own_payload() -> None:
    error = BadRequestException("invalid request", field="name", source="body", reason="missing")

    assert isinstance(error, HttpException)
    assert error.status_code == 400
    assert error.to_payload() == {
        "detail": "invalid request",
        "field": "name",
        "source": "body",
        "reason": "missing",
    }


def test_a_request_refused_for_want_of_an_identity_is_still_a_guard_rejection() -> None:
    # Every caller a guard refused before this class existed is refused by it still: the
    # class narrows how the refusal is reported and nothing about who is refused.
    error = AuthenticationRequiredError("Authentication required")

    assert isinstance(error, GuardRejectedError)
