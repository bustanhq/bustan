"""Unit tests for adapter-route compilation."""

from __future__ import annotations

import pytest
from starlette.requests import Request

from bustan import (
    VERSION_NEUTRAL,
    Controller,
    Get,
    Injectable,
    Module,
    Scope,
    VersioningOptions,
    VersioningType,
)
from bustan.adapters.asgi import AsgiAdapter
from bustan.adapters.asgi.requests import AsgiHttpRequest
from bustan.adapters.starlette import StarletteAdapter
from bustan.contracts import AbstractHttpAdapter, HttpRequest
from bustan.kernel.errors import RouteDefinitionError
from bustan.kernel.ioc.container import build_container
from bustan.kernel.module.graph import build_module_graph
from bustan.runtime.adapter import CompiledAdapterRoute, compile_adapter_routes
from bustan.runtime.compiler import compile_route_contracts
from bustan.runtime.execution import ExecutionPlan


def test_adapter_compiler_consumes_compiled_route_contracts_only() -> None:
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
    route_contracts = compile_route_contracts(graph, container)

    compiled_routes = compile_adapter_routes(
        StarletteAdapter(),
        route_contracts,
        container,
    )

    assert len(compiled_routes) == 1
    assert isinstance(compiled_routes[0], CompiledAdapterRoute)
    assert compiled_routes[0].contracts == (route_contracts[0],)
    assert len(compiled_routes[0].execution_plans) == 1
    assert isinstance(compiled_routes[0].execution_plans[0], ExecutionPlan)
    assert compiled_routes[0].execution_plans[0].route_contract is route_contracts[0]
    assert compiled_routes[0].path == "/users"
    assert compiled_routes[0].methods == ("GET",)


def test_adapter_compiler_preserves_deterministic_order() -> None:
    @Controller("/zeta")
    class ZetaController:
        @Get("/")
        def index(self) -> dict[str, str]:
            return {"controller": "zeta"}

    @Controller("/alpha")
    class AlphaController:
        @Get("/")
        def index(self) -> dict[str, str]:
            return {"controller": "alpha"}

    @Module(controllers=[ZetaController, AlphaController])
    class AppModule:
        pass

    graph = build_module_graph(AppModule)
    container = build_container(graph)
    compiled_routes = compile_adapter_routes(
        StarletteAdapter(),
        compile_route_contracts(graph, container),
        container,
    )

    assert [compiled_route.path for compiled_route in compiled_routes] == ["/zeta", "/alpha"]


def test_the_plan_hands_an_adapter_a_neutral_handler_and_no_transport_object() -> None:
    @Controller("/users", version=VERSION_NEUTRAL)
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
        versioning=VersioningOptions(type=VersioningType.HEADER),
    )

    assert compiled_routes[0].handler is not None
    assert compiled_routes[0].contracts[0].controller_cls is UsersController


def _compile_for(adapter: AbstractHttpAdapter, controller: type[object]) -> None:
    """Compile one controller for *adapter*, which is where a route is refused or accepted."""

    module = Module(controllers=[controller])(type("AppModule", (), {}))
    graph = build_module_graph(module)
    container = build_container(graph)
    compile_adapter_routes(adapter, compile_route_contracts(graph, container), container)


def test_a_handler_naming_another_transport_s_request_type_is_refused_at_assembly() -> None:
    """The wiring is judged where the adapter and the route plan first meet.

    A parameter naming a transport request type the serving adapter does not build could
    only ever be handed the wrong object, and the mistake belongs to how the application
    was assembled rather than to any request, so it is answered once here instead of on
    every call.
    """

    @Controller("/probe")
    class ProbeController:
        @Get("/")
        def probe(self, request: Request) -> None:
            return None

    with pytest.raises(RouteDefinitionError) as info:
        _compile_for(AsgiAdapter(), ProbeController)

    message = str(info.value)
    assert "parameter 'request'" in message
    assert "starlette.requests.Request" in message
    assert "AsgiAdapter" in message
    assert "bustan.adapters.asgi.requests.AsgiHttpRequest" in message


def test_a_handler_naming_the_serving_adapter_s_own_request_type_compiles() -> None:
    """Each adapter accepts the annotation naming the request type it produces."""

    @Controller("/probe")
    class StarletteProbeController:
        @Get("/")
        def probe(self, request: Request) -> None:
            return None

    @Controller("/probe")
    class AsgiProbeController:
        @Get("/")
        def probe(self, request: AsgiHttpRequest) -> None:
            return None

    _compile_for(StarletteAdapter(), StarletteProbeController)
    _compile_for(AsgiAdapter(), AsgiProbeController)


def test_the_neutral_request_contract_compiles_under_every_adapter() -> None:
    """Writing the framework's own request type is what stays true under any transport."""

    @Controller("/probe")
    class NeutralProbeController:
        @Get("/")
        def probe(self, request: HttpRequest) -> None:
            return None

    _compile_for(StarletteAdapter(), NeutralProbeController)
    _compile_for(AsgiAdapter(), NeutralProbeController)


def _compile_for_graph(adapter: AbstractHttpAdapter, module: type[object]) -> None:
    """Compile a whole module for *adapter*, so its providers are judged as well."""

    graph = build_module_graph(module)
    container = build_container(graph)
    compile_adapter_routes(adapter, compile_route_contracts(graph, container), container)


def test_a_provider_constructor_naming_another_transport_s_request_type_is_refused() -> None:
    """A constructor is handed the same object a handler parameter is handed.

    Nothing about the mistake changes because it was written one line further in, so it
    is refused where the wiring is judged and in the same words. The container plan that
    settled the parameter was built before any adapter existed, which is why the answer
    waits until an adapter is in hand rather than being given where the parameter was
    read.
    """

    @Injectable(scope=Scope.REQUEST)
    class HoldsAForeignTransportRequest:
        def __init__(self, request: Request) -> None:
            self.request = request

    @Controller("/probe", scope=Scope.REQUEST)
    class ProbeController:
        def __init__(self, holder: HoldsAForeignTransportRequest) -> None:
            self.holder = holder

        @Get("/")
        def probe(self) -> None:
            return None

    @Module(controllers=[ProbeController], providers=[HoldsAForeignTransportRequest])
    class AppModule:
        pass

    with pytest.raises(RouteDefinitionError) as info:
        _compile_for_graph(AsgiAdapter(), AppModule)

    message = str(info.value)
    assert "HoldsAForeignTransportRequest.__init__ parameter 'request'" in message
    assert "starlette.requests.Request" in message
    assert "AsgiAdapter" in message
    assert "bustan.adapters.asgi.requests.AsgiHttpRequest" in message


def test_a_controller_constructor_naming_another_transport_s_request_type_is_refused() -> None:
    """A controller is planned by the same container, so it is held to the same rule."""

    @Controller("/probe", scope=Scope.REQUEST)
    class ProbeController:
        def __init__(self, request: Request) -> None:
            self.request = request

        @Get("/")
        def probe(self) -> None:
            return None

    @Module(controllers=[ProbeController])
    class AppModule:
        pass

    with pytest.raises(RouteDefinitionError) as info:
        _compile_for_graph(AsgiAdapter(), AppModule)

    assert "ProbeController.__init__ parameter 'request'" in str(info.value)


def test_a_provider_constructor_naming_the_serving_adapter_s_own_request_type_compiles() -> None:
    """Each adapter accepts the constructor annotation naming the type it produces."""

    @Injectable(scope=Scope.REQUEST)
    class HoldsTheStarletteRequest:
        def __init__(self, request: Request) -> None:
            self.request = request

    @Injectable(scope=Scope.REQUEST)
    class HoldsTheAsgiRequest:
        def __init__(self, request: AsgiHttpRequest) -> None:
            self.request = request

    @Injectable(scope=Scope.REQUEST)
    class HoldsTheContract:
        def __init__(self, request: HttpRequest) -> None:
            self.request = request

    @Controller("/probe", scope=Scope.REQUEST)
    class StarletteProbeController:
        def __init__(self, holder: HoldsTheStarletteRequest, neutral: HoldsTheContract) -> None:
            self.holder = holder

        @Get("/")
        def probe(self) -> None:
            return None

    @Controller("/probe", scope=Scope.REQUEST)
    class AsgiProbeController:
        def __init__(self, holder: HoldsTheAsgiRequest, neutral: HoldsTheContract) -> None:
            self.holder = holder

        @Get("/")
        def probe(self) -> None:
            return None

    @Module(
        controllers=[StarletteProbeController],
        providers=[HoldsTheStarletteRequest, HoldsTheContract],
    )
    class StarletteModule:
        pass

    @Module(controllers=[AsgiProbeController], providers=[HoldsTheAsgiRequest, HoldsTheContract])
    class AsgiModule:
        pass

    _compile_for_graph(StarletteAdapter(), StarletteModule)
    _compile_for_graph(AsgiAdapter(), AsgiModule)
