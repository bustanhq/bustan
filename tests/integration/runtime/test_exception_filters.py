"""Integration tests for exception filter matching and fallback behavior."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

import pytest

from bustan import (
    APP_FILTER,
    Controller,
    ExceptionFilter,
    ExecutionContext,
    Get,
    HttpResponse,
    Injectable,
    Module,
    Scope,
    UseFilters,
    ValueProvider,
    create_app,
)
from bustan.errors import BadRequestException, ProviderResolutionError
from bustan.observability.observability import ObservabilityHooks
from bustan.testing import AsgiTestClient


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

    with AsgiTestClient(cast(Any, create_app(AppModule))) as client:
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

    with AsgiTestClient(cast(Any, create_app(AppModule))) as client:
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


def test_a_route_filter_maps_an_exception_a_constructor_raised() -> None:
    # A request-scoped provider is where the documentation puts the authenticated
    # principal, so it is also where authentication and validation failures are
    # raised. The route's own filters are resolved before anything a request pays
    # for is constructed, so such a failure is theirs to map like any other.
    class UnauthenticatedFilter(ExceptionFilter):
        exception_types = (BadRequestException,)

        async def catch(self, exc: Exception, context: ExecutionContext) -> HttpResponse:
            return HttpResponse.json({"detail": "mapped by the route filter"}, status_code=422)

    @Injectable(scope=Scope.REQUEST)
    class CurrentUser:
        def __init__(self) -> None:
            raise BadRequestException("missing header", field="x-user", source="header")

    @Controller("/me", scope=Scope.REQUEST)
    class MeController:
        def __init__(self, current_user: CurrentUser) -> None:
            self._current_user = current_user

        @UseFilters(UnauthenticatedFilter())
        @Get("/")
        def read(self) -> dict[str, str]:
            return {"status": "never reached"}

    @Module(controllers=[MeController], providers=[CurrentUser])
    class AppModule:
        pass

    with AsgiTestClient(cast(Any, create_app(AppModule))) as client:
        response = client.get("/me/")

    assert response.status_code == 422
    assert response.json() == {"detail": "mapped by the route filter"}


def test_an_app_filter_maps_an_exception_a_constructor_raised() -> None:
    class ApplicationFilter(ExceptionFilter):
        exception_types = (BadRequestException,)

        async def catch(self, exc: Exception, context: ExecutionContext) -> HttpResponse:
            return HttpResponse.json({"detail": "mapped by APP_FILTER"}, status_code=422)

    @Injectable(scope=Scope.REQUEST)
    class CurrentUser:
        def __init__(self) -> None:
            raise BadRequestException("missing header", field="x-user", source="header")

    @Controller("/me", scope=Scope.REQUEST)
    class MeController:
        def __init__(self, current_user: CurrentUser) -> None:
            self._current_user = current_user

        @Get("/")
        def read(self) -> dict[str, str]:
            return {"status": "never reached"}

    @Module(
        controllers=[MeController],
        providers=[CurrentUser, ValueProvider(provide=APP_FILTER, use_value=ApplicationFilter())],
    )
    class AppModule:
        pass

    with AsgiTestClient(cast(Any, create_app(AppModule))) as client:
        response = client.get("/me/")

    assert response.status_code == 422
    assert response.json() == {"detail": "mapped by APP_FILTER"}


def test_an_exception_a_constructor_raised_reaches_the_observability_hooks() -> None:
    class RecordingMetrics:
        def __init__(self) -> None:
            self.records: list[dict[str, str]] = []

        def record_request(self, *, labels: Mapping[str, str]) -> None:
            self.records.append(dict(labels))

    @Injectable(scope=Scope.REQUEST)
    class CurrentUser:
        def __init__(self) -> None:
            raise BadRequestException("missing header", field="x-user", source="header")

    @Controller("/me", scope=Scope.REQUEST)
    class MeController:
        def __init__(self, current_user: CurrentUser) -> None:
            self._current_user = current_user

        @Get("/")
        def read(self) -> dict[str, str]:
            return {"status": "never reached"}

    @Module(controllers=[MeController], providers=[CurrentUser])
    class AppModule:
        pass

    metrics = RecordingMetrics()
    with (
        ObservabilityHooks.scoped_override(ObservabilityHooks(metrics=cast(Any, metrics))),
        AsgiTestClient(cast(Any, create_app(AppModule))) as client,
    ):
        response = client.get("/me/")

    # The mapped status, not a fixed one: the same request is counted under the same
    # status the caller was answered with.
    assert response.status_code == 400
    assert [record["status"] for record in metrics.records] == ["400"]
    assert metrics.records[0]["operation"].endswith("read")


def test_an_exception_a_constructor_raised_is_mapped_without_any_declared_filter() -> None:
    @Injectable(scope=Scope.REQUEST)
    class CurrentUser:
        def __init__(self) -> None:
            raise BadRequestException("missing header", field="x-user", source="header")

    @Controller("/me", scope=Scope.REQUEST)
    class MeController:
        def __init__(self, current_user: CurrentUser) -> None:
            self._current_user = current_user

        @Get("/")
        def read(self) -> dict[str, str]:
            return {"status": "never reached"}

    @Module(controllers=[MeController], providers=[CurrentUser])
    class AppModule:
        pass

    with AsgiTestClient(cast(Any, create_app(AppModule))) as client:
        response = client.get("/me/")

    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json() == {
        "type": "https://bustan.dev/problems/bad-request",
        "title": "Bad Request",
        "status": 400,
        "detail": "missing header",
        "instance": "/me",
        "errors": [{"field": "x-user", "source": "header"}],
        "field": "x-user",
        "source": "header",
        "code": "bad-request",
    }


def test_the_application_wide_chain_answers_when_the_route_chain_cannot_be_built() -> None:
    # The route declares a filter that cannot be constructed, so the chain the route
    # would have been answered with does not exist. The application-wide chain is
    # resolved on its own rather than the caller being handed a fixed status.
    class ApplicationFilter(ExceptionFilter):
        exception_types = (Exception,)

        async def catch(self, exc: Exception, context: ExecutionContext) -> HttpResponse:
            return HttpResponse.json({"detail": "mapped by APP_FILTER"}, status_code=503)

    @Injectable(scope=Scope.TRANSIENT)
    class BrokenFilter(ExceptionFilter):
        def __init__(self) -> None:
            raise RuntimeError("filter construction blew up")

    @Controller("/broken")
    class BrokenFilterController:
        @UseFilters(BrokenFilter)
        @Get("/")
        def read(self) -> dict[str, str]:
            return {"status": "never reached"}

    @Module(
        controllers=[BrokenFilterController],
        providers=[BrokenFilter, ValueProvider(provide=APP_FILTER, use_value=ApplicationFilter())],
    )
    class AppModule:
        pass

    with AsgiTestClient(cast(Any, create_app(AppModule))) as client:
        response = client.get("/broken/")

    assert response.status_code == 503
    assert response.json() == {"detail": "mapped by APP_FILTER"}
