"""Unit tests for exception filter matching and fallback behavior."""

from __future__ import annotations

import json
from typing import Any, cast

import pytest
from starlette.requests import Request

from bustan.adapters.starlette import StarletteHttpRequest
from bustan.common.types import RouteMetadata
from bustan.contracts import HttpResponse, RateLimitDecision
from bustan.kernel.errors import BadRequestException, GuardRejectedError, ParameterBindingError
from bustan.kernel.module.dynamic import ModuleInstanceKey
from bustan.pipeline.context import ExecutionContext, RequestContext
from bustan.pipeline.filters import (
    ExceptionFilter,
    _exception_distance,
    _matching_filters,
    _problem_errors,
    _problem_status,
    handle_exception,
)
from bustan.runtime.metadata import ControllerRouteDefinition


@pytest.mark.anyio
async def test_more_specific_filters_win_over_broader_matches() -> None:
    class ValueErrorFilter(ExceptionFilter):
        exception_types = (ValueError,)

        async def catch(self, exc: Exception, context: ExecutionContext) -> object:
            return {"detail": "specific"}

    class CatchAllFilter(ExceptionFilter):
        exception_types = (Exception,)

        async def catch(self, exc: Exception, context: ExecutionContext) -> object:
            return {"detail": "broad"}

    result = await handle_exception(
        _request_context("/fails"),
        ValueError("boom"),
        (ValueErrorFilter(), CatchAllFilter()),
    )

    assert result == {"detail": "specific"}


@pytest.mark.anyio
async def test_global_fallback_runs_when_no_custom_filter_matches() -> None:
    result = await handle_exception(_request_context("/fails"), RuntimeError("boom"), ())

    assert isinstance(result, HttpResponse)
    payload = json.loads(result.body)
    assert result.status_code == 500
    assert result.media_type == "application/problem+json"
    assert payload == {
        "type": "about:blank",
        "title": "Internal Server Error",
        "status": 500,
        "detail": "Internal server error",
        "instance": "/fails",
    }


@pytest.mark.anyio
async def test_rfc7807_payloads_include_stable_fields_and_status_codes() -> None:
    result = await handle_exception(
        _request_context("/users/not-a-number"),
        ParameterBindingError(
            "Could not bind path parameter 'user_id' to int",
            field="user_id",
            source="path parameter",
            reason="invalid integer",
        ),
        (),
    )

    assert isinstance(result, HttpResponse)
    payload = json.loads(result.body)
    assert result.status_code == 400
    assert payload == {
        "type": "about:blank",
        "title": "Bad Request",
        "status": 400,
        "detail": "Could not bind path parameter 'user_id' to int",
        "instance": "/users/not-a-number",
        "field": "user_id",
        "source": "path parameter",
        "reason": "invalid integer",
        "errors": [
            {
                "field": "user_id",
                "source": "path parameter",
                "reason": "invalid integer",
            }
        ],
    }


@pytest.mark.anyio
async def test_base_exception_filter_re_raises_the_original_exception() -> None:
    with pytest.raises(RuntimeError, match="boom"):
        ExceptionFilter().catch(RuntimeError("boom"), _request_context("/fails"))


@pytest.mark.anyio
async def test_handle_exception_falls_back_after_reentered_filter_failures() -> None:
    class ValueErrorFilter(ExceptionFilter):
        exception_types = (ValueError,)

        async def catch(self, exc: Exception, context: ExecutionContext) -> object:
            raise KeyError("replacement")

    class KeyErrorFilter(ExceptionFilter):
        exception_types = (KeyError,)

        async def catch(self, exc: Exception, context: ExecutionContext) -> object:
            raise RuntimeError("filter boom")

    result = await handle_exception(
        _request_context("/fails"),
        ValueError("boom"),
        (ValueErrorFilter(), KeyErrorFilter()),
    )

    assert isinstance(result, HttpResponse)
    payload = json.loads(result.body)
    assert result.status_code == 500
    assert payload["detail"] == "Internal server error"


@pytest.mark.anyio
async def test_a_guard_rejection_body_carries_a_fixed_reason() -> None:
    disclosing_reasons = (
        "Guard app.security.guards.InternalOnlyGuard blocked the request",
        "Unknown authenticator registry for strategy 'acme-hmac-v2'",
    )

    for reason in disclosing_reasons:
        result = await handle_exception(
            _request_context("/secret"),
            GuardRejectedError(reason),
            (),
        )

        assert isinstance(result, HttpResponse)
        assert result.status_code == 403
        assert json.loads(result.body) == {
            "type": "about:blank",
            "title": "Forbidden",
            "status": 403,
            "detail": "Forbidden",
            "instance": "/secret",
        }
        assert reason not in result.body.decode("utf-8")


@pytest.mark.anyio
async def test_a_throttled_request_is_told_the_status_and_not_the_guard() -> None:
    context = _request_context("/secret")
    context.request.slots.rate_limit = RateLimitDecision(
        limit=1, remaining=0, reset=30, exceeded=True
    )

    result = await handle_exception(
        context,
        GuardRejectedError("Guard bustan.security.throttler.ThrottlerGuard blocked the request"),
        (),
    )

    assert isinstance(result, HttpResponse)
    assert result.status_code == 429
    assert json.loads(result.body)["detail"] == "Too Many Requests"
    assert "ThrottlerGuard" not in result.body.decode("utf-8")


@pytest.mark.anyio
async def test_a_validation_message_still_reaches_the_caller_that_caused_it() -> None:
    result = await handle_exception(
        _request_context("/users/not-a-number"),
        BadRequestException("Validation failed (integer expected)", field="user_id"),
        (),
    )

    assert isinstance(result, HttpResponse)
    assert result.status_code == 400
    assert json.loads(result.body)["detail"] == "Validation failed (integer expected)"


def test_filter_matching_and_problem_helpers_cover_remaining_branches() -> None:
    class ValueErrorFilter(ExceptionFilter):
        exception_types = (ValueError,)

    class CatchAllFilter(ExceptionFilter):
        exception_types = (Exception,)

    catch_all_filter = CatchAllFilter()
    value_error_filter = ValueErrorFilter()
    context = _request_context("/fails")
    context.request.slots.rate_limit = RateLimitDecision(
        limit=1, remaining=0, reset=30, exceeded=True
    )

    assert _matching_filters(RuntimeError("boom"), (value_error_filter,)) == ()
    assert _matching_filters(
        ValueError("boom"),
        (catch_all_filter, value_error_filter),
    ) == (value_error_filter, catch_all_filter)
    assert _exception_distance(ValueError, KeyError) == len(ValueError.__mro__)
    assert _problem_status(
        GuardRejectedError("limited"),
        context,
    ) == (429, "Too Many Requests")
    assert _problem_errors(RuntimeError("boom")) is None

    bad_request = BadRequestException("invalid", field="name", source="body", reason="missing")
    assert _problem_errors(bad_request) == [
        {"field": "name", "source": "body", "reason": "missing"}
    ]


def _request_context(path: str) -> RequestContext:
    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    request = Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("utf-8"),
            "query_string": b"",
            "headers": [(b"host", b"testserver")],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
            "path_params": {},
        },
        receive,
    )
    return RequestContext(
        request=StarletteHttpRequest(request),
        module=ModuleInstanceKey(module=object, instance_id="test"),
        controller_type=object,
        controller=object(),
        route=ControllerRouteDefinition(
            handler_name="test",
            handler=_handler,
            route=RouteMetadata(method="GET", path=path, name="test"),
        ),
        container=cast(Any, object()),
    )


def _handler() -> None:
    return None
