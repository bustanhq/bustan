"""Integration tests for exception filter matching and fallback behavior."""

from __future__ import annotations

from typing import Any, cast

import pytest
from starlette.testclient import TestClient

from bustan import (
    Controller,
    ExceptionFilter,
    ExecutionContext,
    Get,
    Injectable,
    Module,
    Scope,
    UseFilters,
    create_app,
)
from bustan.errors import ProviderResolutionError


def test_create_app_prefers_specific_filters_over_catch_all_filters() -> None:
    class ValueErrorFilter(ExceptionFilter):
        exception_types = (ValueError,)

        async def catch(self, exc: Exception, context: ExecutionContext) -> object:
            request = context.request
            assert request is not None
            return {"detail": "specific", "path": request.path}

    class CatchAllFilter(ExceptionFilter):
        exception_types = (Exception,)

        async def catch(self, exc: Exception, context: ExecutionContext) -> object:
            return {"detail": "catch-all"}

    @Controller("/fails")
    class FailingController:
        @UseFilters(ValueErrorFilter(), CatchAllFilter())
        @Get("/")
        def explode(self) -> None:
            raise ValueError("boom")

    @Module(controllers=[FailingController])
    class AppModule:
        pass

    with TestClient(cast(Any, create_app(AppModule))) as client:
        response = client.get("/fails")

    assert response.status_code == 200
    assert response.json() == {"detail": "specific", "path": "/fails"}


def test_create_app_returns_problem_details_for_unhandled_exceptions() -> None:
    @Controller("/fails")
    class FailingController:
        @Get("/")
        def explode(self) -> None:
            raise RuntimeError("boom")

    @Module(controllers=[FailingController])
    class AppModule:
        pass

    with TestClient(cast(Any, create_app(AppModule))) as client:
        response = client.get("/fails")

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json() == {
        "type": "about:blank",
        "title": "Internal Server Error",
        "status": 500,
        "detail": "Internal server error",
        "instance": "/fails",
    }


def test_create_app_refuses_a_default_scope_controller_holding_a_request_scoped_provider() -> None:
    # A controller declared without a scope is constructed once and cached for the
    # process, so a request-scoped provider in its constructor pins the first
    # caller's per-request state and serves it to everyone after: one caller's
    # identity, headers and cookies answered to the next. The composition is
    # therefore refused while the application is built, before any request exists to
    # observe it, and never reported as a runtime failure that a filter might mask.
    @Injectable(scope=Scope.REQUEST)
    class RequestScopedService:
        pass

    @Controller("/fails")
    class FailingController:
        def __init__(self, request_scoped_service: RequestScopedService) -> None:
            self._request_scoped_service = request_scoped_service

        @Get("/")
        def read(self) -> dict[str, str]:
            return {"status": "ok"}

    @Module(controllers=[FailingController], providers=[RequestScopedService])
    class AppModule:
        pass

    with pytest.raises(ProviderResolutionError, match="request-scoped"):
        create_app(AppModule)
