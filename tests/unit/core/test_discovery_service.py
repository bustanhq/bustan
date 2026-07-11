"""Unit tests for the discovery addon surface."""

from __future__ import annotations

from bustan import Controller, DiscoveryModule, DiscoveryService, Get, Injectable, Module, create_app


def test_discovery_service_enumerates_modules_providers_and_routes() -> None:
    @Injectable
    class GreetingService:
        pass

    @Controller("/greetings")
    class GreetingController:
        @Get("/")
        def read_greeting(self) -> dict[str, str]:
            return {"message": "hello"}

    @Module(
        imports=[DiscoveryModule],
        controllers=[GreetingController],
        providers=[GreetingService],
        exports=[GreetingService],
    )
    class AppModule:
        pass

    application = create_app(AppModule)
    discovery = application.get(DiscoveryService)

    modules = discovery.modules()
    providers = discovery.providers()
    routes = discovery.routes()

    assert [entry["module"] for entry in modules] == ["AppModule", "DiscoveryModule"]
    assert modules[0]["controllers"] == ("GreetingController",)
    assert [entry["token"] for entry in providers] == [
        "GreetingService",
        "DiscoveryService",
        "ModuleRef",
    ]
    assert len(routes) == 1
    assert routes[0]["controller"] == "GreetingController"
    assert routes[0]["path"] == "/greetings"


def test_discovery_service_preserves_deterministic_order() -> None:
    @Injectable
    class ZetaService:
        pass

    @Injectable
    class AlphaService:
        pass

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

    @Module(
        imports=[DiscoveryModule],
        controllers=[ZetaController, AlphaController],
        providers=[ZetaService, AlphaService],
        exports=[ZetaService, AlphaService],
    )
    class AppModule:
        pass

    discovery = create_app(AppModule).get(DiscoveryService)

    assert discovery.modules() == discovery.modules()
    assert [entry["token"] for entry in discovery.providers_for_module(AppModule)] == [
        "AlphaService",
        "ZetaService",
    ]
    assert [entry["path"] for entry in discovery.routes()] == ["/alpha", "/zeta"]


def test_discovery_service_does_not_mutate_container_state() -> None:
    @Injectable
    class GreetingService:
        pass

    @Controller("/greetings")
    class GreetingController:
        @Get("/")
        def read_greeting(self) -> dict[str, str]:
            return {"message": "hello"}

    @Module(
        imports=[DiscoveryModule],
        controllers=[GreetingController],
        providers=[GreetingService],
        exports=[GreetingService],
    )
    class AppModule:
        pass

    application = create_app(AppModule)
    discovery = application.get(DiscoveryService)
    binding_count = len(application.container.registry.bindings)
    routes_before = application.snapshot_routes()

    discovery.modules()
    discovery.providers()
    discovery.routes()

    assert len(application.container.registry.bindings) == binding_count
    assert not application.container.has_override(GreetingService)
    assert application.snapshot_routes() == routes_before