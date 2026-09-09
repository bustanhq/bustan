"""A request that fails in a middleware is answered like one that fails in a handler."""

from __future__ import annotations

from typing import Any, cast

from bustan import (
    APP_FILTER,
    Controller,
    ExceptionFilter,
    ExecutionContext,
    Get,
    HttpResponse,
    Middleware,
    Module,
    UseFilters,
    ValueProvider,
    create_app,
)
from bustan.contracts import HttpRequest
from bustan.kernel.errors import BadRequestException
from bustan.pipeline.middleware import MiddlewareConsumer
from bustan.testing import AsgiTestClient


class FailingMiddleware(Middleware):
    async def use(self, request: HttpRequest, call_next):
        raise BadRequestException("middleware refused the request")


def _client(module: type[object], *, debug: bool = False) -> AsgiTestClient:
    return AsgiTestClient(cast(Any, create_app(module, debug=debug)))


def test_the_middleware_failure_path_answers_in_the_same_content_type() -> None:
    @Controller("/handler")
    class HandlerController:
        @Get("/")
        def index(self) -> dict[str, str]:
            raise BadRequestException("the handler refused the request")

    @Controller("/middleware")
    class MiddlewareController:
        @Get("/")
        def index(self) -> dict[str, str]:
            return {"status": "never reached"}

    @Module(controllers=[HandlerController, MiddlewareController])
    class AppModule:
        def configure(self, consumer: MiddlewareConsumer) -> None:
            consumer.apply(FailingMiddleware).for_routes("/middleware*")

    with _client(AppModule) as client:
        from_handler = client.get("/handler")
        from_middleware = client.get("/middleware")

    assert from_handler.status_code == 400
    assert from_middleware.status_code == 400
    assert from_middleware.headers["content-type"] == from_handler.headers["content-type"]
    assert from_middleware.json()["title"] == from_handler.json()["title"]


def test_a_resolution_failure_on_the_middleware_path_leaks_nothing_under_debug() -> None:
    @Controller("/middleware")
    class BrokenController:
        def __init__(self) -> None:
            raise RuntimeError("controller construction blew up")

        @Get("/")
        def index(self) -> dict[str, str]:
            return {"status": "never reached"}

    @Module(controllers=[BrokenController])
    class AppModule:
        def configure(self, consumer: MiddlewareConsumer) -> None:
            consumer.apply(FailingMiddleware).for_routes("/middleware*")

    with _client(AppModule, debug=True) as client:
        response = client.get("/middleware")

    body = response.text

    # The controller is never built on this path, so the constructor cannot fail and
    # the answer is the one the middleware's own exception maps to.
    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/problem+json")
    assert "Traceback" not in body
    assert "controller construction blew up" not in body
    assert "RuntimeError" not in body
    assert "BrokenController" not in body


def test_the_middleware_failure_path_does_not_construct_the_controller() -> None:
    constructed: list[str] = []

    class MappingFilter(ExceptionFilter):
        exception_types = (BadRequestException,)

        async def catch(self, exc: Exception, context: ExecutionContext) -> HttpResponse:
            return HttpResponse.json({"detail": "mapped by the route filter"}, status_code=422)

    @Controller("/middleware")
    class RecordingController:
        def __init__(self) -> None:
            constructed.append("controller")

        @UseFilters(MappingFilter())
        @Get("/")
        def index(self) -> dict[str, str]:
            return {"status": "never reached"}

    @Module(controllers=[RecordingController])
    class AppModule:
        def configure(self, consumer: MiddlewareConsumer) -> None:
            consumer.apply(FailingMiddleware).for_routes("/middleware*")

    with _client(AppModule) as client:
        response = client.get("/middleware")

    assert response.status_code == 422
    assert response.json() == {"detail": "mapped by the route filter"}
    # Rendering an error needs the filters and the context, not an instance of the
    # controller whose handler the request never reached.
    assert constructed == []


def test_an_app_filter_answers_the_middleware_failure_path() -> None:
    constructed: list[str] = []

    class ApplicationFilter(ExceptionFilter):
        exception_types = (BadRequestException,)

        async def catch(self, exc: Exception, context: ExecutionContext) -> HttpResponse:
            return HttpResponse.json({"detail": "mapped by APP_FILTER"}, status_code=422)

    @Controller("/middleware")
    class RecordingController:
        def __init__(self) -> None:
            constructed.append("controller")

        @Get("/")
        def index(self) -> dict[str, str]:
            return {"status": "never reached"}

    @Module(
        controllers=[RecordingController],
        providers=[ValueProvider(provide=APP_FILTER, use_value=ApplicationFilter())],
    )
    class AppModule:
        def configure(self, consumer: MiddlewareConsumer) -> None:
            consumer.apply(FailingMiddleware).for_routes("/middleware*")

    with _client(AppModule) as client:
        response = client.get("/middleware")

    assert response.status_code == 422
    assert response.json() == {"detail": "mapped by APP_FILTER"}
    assert constructed == []
