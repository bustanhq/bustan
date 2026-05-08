"""Integration tests for exception filter matching and fallback behavior."""

from __future__ import annotations

from typing import Any, cast

from starlette.testclient import TestClient

from bustan import Controller, ExceptionFilter, ExecutionContext, Get, Module, UseFilters, create_app


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
        "detail": "boom",
        "instance": "/fails",
    }