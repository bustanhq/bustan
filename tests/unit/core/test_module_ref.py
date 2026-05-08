"""Unit tests for ModuleRef and public context-id helpers."""

from __future__ import annotations

from typing import Any, cast

import pytest
from starlette.applications import Starlette
from starlette.requests import Request

from bustan import (
    ContextId,
    Controller,
    DiscoveryModule,
    Get,
    Injectable,
    Module,
    ModuleRef,
    application_context_id,
    durable_context_id,
    request_context_id,
    create_app,
)
from bustan.addons.discovery import _resolve_application_context, _resolve_module_node
from bustan.addons.module_ref import _resolve_application, _resolve_module_key


def test_module_ref_resolves_providers_through_public_application_semantics() -> None:
    @Injectable
    class GreetingService:
        def greet(self) -> str:
            return "hello"

    @Module(providers=[GreetingService], exports=[GreetingService])
    class FeatureModule:
        pass

    @Controller("/greetings")
    class GreetingController:
        @Get("/")
        def read_greeting(self) -> dict[str, str]:
            return {"message": "hello"}

    @Module(imports=[FeatureModule, DiscoveryModule], controllers=[GreetingController])
    class AppModule:
        pass

    application = create_app(AppModule)
    module_ref = application.get(ModuleRef)
    feature_ref = module_ref.for_module(FeatureModule)

    assert module_ref.module_key is AppModule
    assert feature_ref.module_key is FeatureModule
    assert module_ref.get(GreetingService, strict=False) is application.get(GreetingService)
    assert feature_ref.get(GreetingService) is application.container.resolve(
        GreetingService,
        module=FeatureModule,
    )


def test_context_ids_are_deterministic_and_scope_safe() -> None:
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/health",
        "raw_path": b"/health",
        "query_string": b"",
        "headers": [(b"host", b"testserver")],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
        "path_params": {},
    }

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    request = Request(scope, receive)

    class DurableKeyProvider:
        @classmethod
        def get_durable_context_key(cls, request: Request | None) -> str:
            return "users"

    application_id = application_context_id(type("AppModule", (), {}))
    request_id = request_context_id(request)
    durable_id = durable_context_id(DurableKeyProvider, request)

    assert application_id == application_context_id(type("AppModule", (), {}))
    assert request_id == request_context_id(request)
    assert durable_id == durable_context_id(DurableKeyProvider, request)
    assert isinstance(application_id, ContextId)
    assert application_id.scope == "application"
    assert request_id.scope == "request"
    assert durable_id.scope == "durable"
    assert request_context_id(None) == ContextId(scope="request", value="none")
    assert len({application_id, request_id, durable_id}) == 3


def test_module_ref_create_and_helper_error_paths_are_covered() -> None:
    @Injectable
    class GreetingService:
        def greet(self) -> str:
            return "hello"

    @Module(providers=[GreetingService], exports=[GreetingService])
    class FeatureModule:
        pass

    @Injectable
    class GreetingConsumer:
        def __init__(self, greeting_service: GreetingService) -> None:
            self.greeting_service = greeting_service

    @Controller("/greetings")
    class GreetingController:
        @Get("/")
        def read_greeting(self) -> dict[str, str]:
            return {"message": "hello"}

    @Module(imports=[FeatureModule, DiscoveryModule], controllers=[GreetingController])
    class AppModule:
        pass

    application = create_app(AppModule)
    module_ref = application.get(ModuleRef).for_module(FeatureModule)
    consumer = module_ref.create(GreetingConsumer)

    assert consumer.greeting_service.greet() == "hello"
    assert module_ref.resolve(GreetingService) is module_ref.get(GreetingService)

    with pytest.raises(KeyError, match="Unknown module"):
        _resolve_module_key(application, cast(Any, object()))

    with pytest.raises(TypeError, match="Application runtime"):
        _resolve_application(object())

    bare_starlette = Starlette()
    with pytest.raises(TypeError, match="Application runtime"):
        _resolve_application(bare_starlette)


def test_discovery_helper_error_paths_are_covered() -> None:
    @Injectable
    class GreetingService:
        pass

    @Controller("/greetings")
    class GreetingController:
        @Get("/")
        def read_greeting(self) -> dict[str, str]:
            return {"message": "hello"}

    @Module(imports=[DiscoveryModule], controllers=[GreetingController], providers=[GreetingService])
    class AppModule:
        pass

    application = create_app(AppModule)

    with pytest.raises(KeyError, match="Unknown module"):
        _resolve_module_node(application.module_graph.nodes, cast(Any, object()))

    with pytest.raises(TypeError, match="Application runtime"):
        _resolve_application_context(object())

    bare_starlette = Starlette()
    with pytest.raises(TypeError, match="Application runtime"):
        _resolve_application_context(bare_starlette)

    starlette = Starlette()
    starlette.state.bustan_application = application
    assert _resolve_application(starlette) is application
    assert _resolve_application_context(starlette) is application