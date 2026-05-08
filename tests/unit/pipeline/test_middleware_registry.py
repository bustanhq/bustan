"""Unit tests for compiled middleware registry resolution."""

from __future__ import annotations

import pytest
from starlette.requests import Request
from starlette.responses import Response

from bustan import Controller, Get, Module, Post
from bustan.core.ioc.container import build_container
from bustan.core.module.graph import build_module_graph
from bustan.pipeline.middleware import (
    ConditionalMiddleware,
    Middleware,
    MiddlewareRouteTarget,
    RequestMethod,
    RouteInfo,
    _normalize_host_pattern,
    _route_host_matches,
    _normalize_route_target,
    compile_middleware_registry,
    path_matches,
)
from bustan.platform.http.compiler import compile_route_contracts


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
        contract
        for contract in contracts
        if contract.path == "/users" and contract.method == "GET"
    )
    post_contract = next(
        contract
        for contract in contracts
        if contract.path == "/users" and contract.method == "POST"
    )

    assert registry.resolve_for(get_contract) == ()
    assert [entry.middleware for entry in registry.resolve_for(post_contract)] == [
        ScopedMiddleware
    ]


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
async def test_conditional_middleware_dispatch_covers_sync_and_bypass_paths() -> None:
    events: list[str] = []

    def sync_handler(request: Request, call_next) -> Response:
        events.append("handled")
        return Response(content=b"handled", status_code=201)

    middleware = ConditionalMiddleware(
        lambda scope, receive, send: None,
        handler=sync_handler,
        include=("/users/*",),
    )

    async def call_next(current_request: Request) -> Response:
        events.append("next")
        return Response(content=b"next", status_code=200)

    handled_response = await middleware.dispatch(_build_request("/users/123"), call_next)
    bypass_response = await middleware.dispatch(_build_request("/health"), call_next)

    assert handled_response.status_code == 201
    assert bypass_response.status_code == 200
    assert events == ["handled", "next"]


@pytest.mark.anyio
async def test_middleware_base_use_and_exclude_paths_are_supported() -> None:
    async def call_next(current_request: Request) -> Response:
        return Response(content=b"next", status_code=200)

    request = _build_request("/users/skip")
    assert (await Middleware().use(request, call_next)).status_code == 200

    class AsyncMiddleware(Middleware):
        async def use(self, request: Request, call_next) -> Response:
            return Response(content=b"middleware", status_code=202)

    middleware = ConditionalMiddleware(
        lambda scope, receive, send: None,
        handler=AsyncMiddleware(),
        include=("/users/*",),
        exclude=("/users/skip",),
    )

    excluded_response = await middleware.dispatch(request, call_next)
    handled_response = await middleware.dispatch(_build_request("/users/run"), call_next)

    assert excluded_response.status_code == 200
    assert handled_response.status_code == 202


def _build_request(path: str) -> Request:
    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(
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