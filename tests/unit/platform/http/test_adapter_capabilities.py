"""Unit tests for adapter capability validation."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from bustan import Controller, Get, Module, Post
from bustan.core.errors import RouteDefinitionError
from bustan.core.ioc.container import build_container
from bustan.core.module.graph import build_module_graph
from bustan.platform.http.adapter import AbstractHttpAdapter, AdapterCapabilities, compile_adapter_routes
from bustan.platform.http.adapters.starlette_adapter import StarletteAdapter
from bustan.platform.http.compiler import ResponseStrategy, compile_route_contracts


class BodylessStarletteAdapter(StarletteAdapter):
    capabilities = AdapterCapabilities(
        supports_host_routing=False,
        supports_raw_body=False,
        supports_streaming_responses=True,
        supports_websocket_upgrade=False,
    )


class StreamlessStarletteAdapter(StarletteAdapter):
    capabilities = AdapterCapabilities(
        supports_host_routing=False,
        supports_raw_body=True,
        supports_streaming_responses=False,
        supports_websocket_upgrade=False,
    )


class SuperDelegatingAdapter(AbstractHttpAdapter):
    name = "super-delegating"
    capabilities = AdapterCapabilities()

    def get_instance(self):
        return super().get_instance()

    def register_routes(self, routes):
        return super().register_routes(routes)

    def add_middleware(self, middleware_class: type, **options):
        return super().add_middleware(middleware_class, **options)

    async def listen(self, port: int, host: str = "127.0.0.1", reload: bool = False, **kwargs):
        return await super().listen(port, host=host, reload=reload, **kwargs)

    async def close(self):
        return await super().close()

    async def __call__(self, scope: dict, receive, send):
        return await super().__call__(scope, receive, send)


def test_unsupported_raw_body_capability_fails_during_startup_compilation() -> None:
    @Controller("/users")
    class UsersController:
        @Post("/")
        def create_user(self, payload: dict[str, object]) -> dict[str, object]:
            return payload

    @Module(controllers=[UsersController])
    class AppModule:
        pass

    graph = build_module_graph(AppModule)
    container = build_container(graph)

    with pytest.raises(RouteDefinitionError, match="raw body access"):
        compile_adapter_routes(
            BodylessStarletteAdapter(),
            compile_route_contracts(graph, container),
            container,
        )


def test_supported_capabilities_allow_route_registration_to_proceed() -> None:
    @Controller("/users")
    class UsersController:
        @Get("/")
        def index(self) -> dict[str, str]:
            return {"status": "ok"}

    @Module(controllers=[UsersController])
    class AppModule:
        pass

    graph = build_module_graph(AppModule)
    container = build_container(graph)
    compiled_routes = compile_adapter_routes(
        StarletteAdapter(),
        compile_route_contracts(graph, container),
        container,
    )

    assert len(compiled_routes) == 1


def test_host_routing_and_streaming_capabilities_fail_when_unsupported() -> None:
    @Controller("/users", host="api.example.test")
    class UsersController:
        @Get("/")
        def index(self) -> dict[str, str]:
            return {"status": "ok"}

    @Controller("/streams")
    class StreamController:
        @Get("/")
        def stream(self) -> Iterator[bytes]:
            yield b"hello"

    @Module(controllers=[UsersController, StreamController])
    class AppModule:
        pass

    graph = build_module_graph(AppModule)
    container = build_container(graph)
    contracts = compile_route_contracts(graph, container)
    users_contract = next(contract for contract in contracts if contract.path == "/users")
    stream_contract = next(contract for contract in contracts if contract.path == "/streams")

    with pytest.raises(RouteDefinitionError, match="host routing"):
        compile_adapter_routes(
            StarletteAdapter(),
            (users_contract,),
            container,
        )

    assert stream_contract.response_plan.strategy is ResponseStrategy.STREAM
    with pytest.raises(RouteDefinitionError, match="streaming responses"):
        compile_adapter_routes(StreamlessStarletteAdapter(), (stream_contract,), container)


@pytest.mark.anyio
async def test_abstract_http_adapter_base_methods_can_be_delegated_to_super() -> None:
    adapter = SuperDelegatingAdapter()

    assert adapter.get_instance() is None
    assert adapter.register_routes([]) is None
    assert adapter.add_middleware(type("Middleware", (), {})) is None
    assert await adapter.listen(8000) is None
    assert await adapter.close() is None
    assert await adapter({}, lambda: None, lambda message=None: None) is None


def test_compile_adapter_routes_rejects_unsupported_adapter_types() -> None:
    with pytest.raises(TypeError, match="Unsupported HTTP adapter"):
        compile_adapter_routes(SuperDelegatingAdapter(), (), container=None)