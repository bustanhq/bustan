"""Unit tests for Inject, OptionalDep, and special DI tokens."""

from __future__ import annotations

from typing import Annotated, Any, cast

import pytest
from starlette.requests import Request

from bustan import (
    APPLICATION,
    REQUEST,
    Inject,
    Injectable,
    InjectionToken,
    Module,
    OptionalDep,
    create_app_context,
)
from bustan.core.errors import ProviderResolutionError
from bustan.core.ioc.container import build_container
from bustan.core.module.graph import build_module_graph

CONFIG_TOKEN = InjectionToken[str]("CONFIG")
MISSING_TOKEN = InjectionToken[object]("MISSING")


def test_explicit_inject_overrides_annotation_based_resolution() -> None:
    @Injectable
    class ConfigConsumer:
        def __init__(self, config: Annotated[str, Inject(CONFIG_TOKEN)]) -> None:
            self.config = config

    @Module(
        providers=[ConfigConsumer, {"provide": CONFIG_TOKEN, "use_value": "configured"}],
        exports=[ConfigConsumer],
    )
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    consumer = cast(Any, container.resolve(ConfigConsumer, module=AppModule))

    assert consumer.config == "configured"


def test_optional_dependency_returns_none_only_when_marked_optional() -> None:
    @Injectable
    class OptionalConsumer:
        def __init__(
            self,
            maybe: Annotated[object | None, Inject(MISSING_TOKEN), OptionalDep()],
        ) -> None:
            self.maybe = maybe

    @Injectable
    class RequiredConsumer:
        def __init__(self, maybe: Annotated[object, Inject(MISSING_TOKEN)]) -> None:
            self.maybe = maybe

    @Module(providers=[OptionalConsumer, RequiredConsumer])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    optional_consumer = cast(Any, container.resolve(OptionalConsumer, module=AppModule))

    assert optional_consumer.maybe is None

    with pytest.raises(ProviderResolutionError, match="MISSING"):
        container.resolve(RequiredConsumer, module=AppModule)


def test_special_request_token_is_rejected_outside_request_scope() -> None:
    @Injectable
    class RequestAwareService:
        def __init__(self, request: Annotated[object, Inject(REQUEST)]) -> None:
            self.request = request

    @Module(providers=[RequestAwareService])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))

    with pytest.raises(ProviderResolutionError, match="REQUEST"):
        container.resolve(RequestAwareService, module=AppModule)


def test_special_request_token_resolves_within_request_scope() -> None:
    @Injectable(scope="request")
    class RequestAwareService:
        def __init__(self, request: Annotated[object, Inject(REQUEST)]) -> None:
            self.request = request

    @Module(providers=[RequestAwareService], exports=[RequestAwareService])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    request = _build_request("/request-aware")

    service = cast(Any, container.resolve(RequestAwareService, module=AppModule, request=request))

    assert service.request is request


def test_application_token_resolves_in_application_context() -> None:
    @Injectable
    class AppAwareService:
        def __init__(self, app: Annotated[object, Inject(APPLICATION)]) -> None:
            self.app = app

    @Module(providers=[AppAwareService], exports=[AppAwareService])
    class AppModule:
        pass

    context = create_app_context(AppModule)
    service = context.get(AppAwareService)

    assert service.app is context


def _build_request(path: str) -> Request:
    scope = {
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
    }

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(scope, receive)
