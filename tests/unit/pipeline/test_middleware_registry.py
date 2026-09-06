"""Unit tests for compiled middleware registry resolution."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from bustan import Controller, Get, Module, Post
from bustan.adapters.starlette import StarletteHttpRequest
from bustan.contracts import HttpRequest, HttpResponse
from bustan.kernel.ioc.container import build_container
from bustan.kernel.module.graph import build_module_graph
from bustan.pipeline.middleware import (
    Middleware,
    MiddlewareRouteTarget,
    RequestMethod,
    RouteInfo,
    _normalize_host_pattern,
    _normalize_route_target,
    _route_host_matches,
    compile_middleware_registry,
    path_matches,
)
from bustan.runtime.compiler import compile_route_contracts

if TYPE_CHECKING:
    from tests.conftest import RequestFactory


class RootMiddleware:
    pass


class UsersMiddleware:
    pass


class ScopedMiddleware:
    pass


def test_compile_middleware_registry_matches_controller_host_and_module_order() -> None:
    @Controller("/users", host="api.example.test")
    class UsersController:
        @Get("/")
        def read_users(self) -> dict[str, str]:
            return {"status": "ok"}

    @Controller("/health")
    class HealthController:
        @Get("/")
        def read_health(self) -> dict[str, str]:
            return {"status": "up"}

    @Module(controllers=[UsersController])
    class UsersModule:
        def configure(self, consumer) -> None:
            consumer.apply(UsersMiddleware).for_routes(
                RouteInfo(
                    path="/users",
                    method=RequestMethod.GET,
                    host="api.example.test",
                )
            )

    @Module(imports=[UsersModule], controllers=[HealthController])
    class AppModule:
        def configure(self, consumer) -> None:
            consumer.apply(RootMiddleware).for_routes(UsersController)

    graph = build_module_graph(AppModule)
    container = build_container(graph)
    registry = compile_middleware_registry(graph)
    contracts = compile_route_contracts(graph, container)

    users_contract = next(contract for contract in contracts if contract.path == "/users")
    health_contract = next(contract for contract in contracts if contract.path == "/health")

    resolved_middlewares = registry.resolve_for(users_contract)

    assert [entry.middleware for entry in resolved_middlewares] == [
        RootMiddleware,
        UsersMiddleware,
    ]
    assert registry.resolve_for(health_contract) == ()


def test_compile_middleware_registry_applies_exclusions_after_includes() -> None:
    @Controller("/users")
    class UsersController:
        @Get("/")
        def read_users(self) -> dict[str, str]:
            return {"status": "ok"}

        @Post("/")
        def create_user(self) -> dict[str, str]:
            return {"status": "created"}

    @Module(controllers=[UsersController])
    class AppModule:
        def configure(self, consumer) -> None:
            consumer.apply(ScopedMiddleware).for_routes(UsersController).exclude(
                RouteInfo(path="/users", method=RequestMethod.GET)
            )

    graph = build_module_graph(AppModule)
    container = build_container(graph)
    registry = compile_middleware_registry(graph)
    contracts = compile_route_contracts(graph, container)

    get_contract = next(
        contract for contract in contracts if contract.path == "/users" and contract.method == "GET"
    )
    post_contract = next(
        contract
        for contract in contracts
        if contract.path == "/users" and contract.method == "POST"
    )

    assert registry.resolve_for(get_contract) == ()
    assert [entry.middleware for entry in registry.resolve_for(post_contract)] == [ScopedMiddleware]


def test_middleware_helpers_cover_path_matching_host_patterns_and_invalid_targets() -> None:
    assert path_matches("/users/123", ["/users/*"])
    assert path_matches("/users", [])
    assert not path_matches("/health", ["/users/*"])
    assert _normalize_host_pattern("api.:region.example.test") == "api.*.example.test"
    assert _normalize_host_pattern("api.example.test") == "api.example.test"
    assert _route_host_matches(("api.us.example.test",), "api.:region.example.test")
    assert not _route_host_matches((), "api.:region.example.test")

    assert _normalize_route_target("/users", {}) == MiddlewareRouteTarget(path="/users")
    assert _normalize_route_target(
        RouteInfo(path="/users", method=RequestMethod.POST, host="api.example.test"),
        {},
    ) == MiddlewareRouteTarget(
        path="/users",
        method=RequestMethod.POST,
        host="api.example.test",
    )

    with pytest.raises(TypeError, match="Unsupported middleware route target"):
        _normalize_route_target(object(), {})


@pytest.mark.anyio
async def test_the_middleware_base_class_passes_the_request_on_untouched(
    build_request: RequestFactory,
) -> None:
    async def call_next(current_request: HttpRequest) -> HttpResponse:
        return HttpResponse(status_code=200, body=b"next")

    request = StarletteHttpRequest(build_request(path="/users/skip"))
    response = await Middleware().use(request, call_next)

    assert isinstance(response, HttpResponse)
    assert response.status_code == 200


def test_the_public_middleware_base_class_needs_no_web_server_to_subclass() -> None:
    import sys

    module = sys.modules[Middleware.__module__]
    source = Path(module.__file__ or "").read_text()

    assert "starlette" not in source.lower()


@pytest.mark.anyio
async def test_a_middleware_may_answer_the_request_itself(
    build_request: RequestFactory,
) -> None:
    class ShortCircuit(Middleware):
        async def use(self, request: HttpRequest, call_next) -> HttpResponse:
            return HttpResponse.json({"path": request.path}, status_code=202)

    called = False

    async def call_next(current_request: HttpRequest) -> HttpResponse:
        nonlocal called
        called = True
        return HttpResponse()

    response = await ShortCircuit().use(StarletteHttpRequest(build_request(path="/x")), call_next)

    assert isinstance(response, HttpResponse)
    assert response.status_code == 202
    assert not called
