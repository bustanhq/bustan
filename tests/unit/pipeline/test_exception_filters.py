"""Unit tests for exception filter matching and fallback behavior."""

from __future__ import annotations

import json
from typing import Any, cast

import pytest
from starlette.requests import Request

from bustan.common.types import RouteMetadata
from bustan.core.errors import BadRequestException, GuardRejectedError, ParameterBindingError
from bustan.core.module.dynamic import ModuleInstanceKey
from bustan.pipeline.filters import (
    ExceptionFilter,
    _exception_distance,
    _matching_filters,
    _problem_errors,
    _problem_status,
    handle_exception,
)
from bustan.pipeline.context import ExecutionContext, RequestContext
from bustan.platform.http.abstractions import HttpResponse
from bustan.platform.http.metadata import ControllerRouteDefinition


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


def test_filter_matching_and_problem_helpers_cover_remaining_branches() -> None:
    class ValueErrorFilter(ExceptionFilter):
        exception_types = (ValueError,)

    class CatchAllFilter(ExceptionFilter):
        exception_types = (Exception,)

    catch_all_filter = CatchAllFilter()
    value_error_filter = ValueErrorFilter()
    context = _request_context("/fails")
    context.request.state.rate_limit_exceeded = True

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
        request=request,
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