"""Unit tests for adapter capability validation and the port's own surface."""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, cast

import pytest

from bustan import Controller, Get, Module, Post
from bustan.adapters.starlette import StarletteAdapter
from bustan.contracts import HttpRequest
from bustan.kernel.errors import RouteDefinitionError
from bustan.kernel.ioc.container import build_container
from bustan.kernel.module.graph import build_module_graph
from bustan.runtime.adapter import (
    AbstractHttpAdapter,
    AdapterCapabilities,
    compile_adapter_routes,
)
from bustan.runtime.compiler import ResponseStrategy, compile_route_contracts

if TYPE_CHECKING:
    from collections.abc import Sequence

    from bustan.contracts import AdapterRoute


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


class MinimalAdapter(AbstractHttpAdapter):
    """The smallest adapter the port admits, written without naming a transport."""

    name = "minimal"
    capabilities = AdapterCapabilities(supports_raw_body=True)

    def __init__(self) -> None:
        self.registered: tuple[AdapterRoute, ...] = ()
        self.stopped = False

    def from_native_request(self, native_request: object) -> HttpRequest:
        return cast(HttpRequest, native_request)

    def to_native_response(self, response: object) -> object:
        return response

    def register_routes(self, routes: Sequence[AdapterRoute]) -> None:
        self.registered = tuple(routes)

    async def start(
        self, port: int, host: str = "127.0.0.1", reload: bool = False, **options: object
    ) -> None:
        return None

    async def stop(self) -> None:
        self.stopped = True

    def create_test_client(self) -> object:
        return object()

    def get_instance(self) -> object:
        return self

    def add_middleware(self, middleware_class: type, **options: object) -> None:
        return None


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


def test_the_port_declares_the_conversions_and_lifecycle_an_adapter_owes() -> None:
    assert AbstractHttpAdapter.__abstractmethods__ >= {
        "from_native_request",
        "to_native_response",
        "start",
        "stop",
        "create_test_client",
    }


def test_no_port_method_asks_for_a_container_or_names_an_asgi_argument() -> None:
    import inspect

    forbidden = {"scope", "receive", "send", "container"}
    for name in dir(AbstractHttpAdapter):
        member = getattr(AbstractHttpAdapter, name)
        if not callable(member) or name.startswith("__") and name != "__call__":
            continue
        parameters = set(inspect.signature(member).parameters)
        assert not parameters & forbidden, f"{name} takes {parameters & forbidden}"


@pytest.mark.anyio
async def test_an_adapter_written_only_against_the_port_serves_the_plan() -> None:
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
    adapter = MinimalAdapter()

    routes = compile_adapter_routes(adapter, compile_route_contracts(graph, container), container)
    adapter.register_routes(list(routes))

    assert [route.path for route in adapter.registered] == ["/users"]
    assert adapter.registered[0].handler is not None
    assert adapter.registered[0].registration is None
    assert await adapter.start(0) is None
    await adapter.stop()
    assert adapter.stopped


@pytest.mark.anyio
async def test_the_ports_default_serve_entry_point_refuses_rather_than_pretending() -> None:
    adapter = MinimalAdapter()

    with pytest.raises(NotImplementedError, match="start"):
        await adapter({}, None, None)
