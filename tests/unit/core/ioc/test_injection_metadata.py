"""Unit tests for Inject, OptionalDep, and special DI tokens."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any, cast

import pytest

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

if TYPE_CHECKING:
    from tests.conftest import RequestFactory

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

    @Module(providers=[OptionalConsumer])
    class OptionalModule:
        pass

    @Module(providers=[RequiredConsumer])
    class RequiredModule:
        pass

    container = build_container(build_module_graph(OptionalModule))
    optional_consumer = cast(Any, container.resolve(OptionalConsumer, module=OptionalModule))

    assert optional_consumer.maybe is None

    # The same token without the marker is a dependency nothing can supply, and a
    # graph containing one is refused where it is declared rather than where it is used.
    with pytest.raises(ProviderResolutionError, match="MISSING"):
        build_container(build_module_graph(RequiredModule))


def test_special_request_token_is_rejected_outside_request_scope() -> None:
    @Injectable
    class RequestAwareService:
        def __init__(self, request: Annotated[object, Inject(REQUEST)]) -> None:
            self.request = request

    @Module(providers=[RequestAwareService])
    class AppModule:
        pass

    with pytest.raises(ProviderResolutionError, match="REQUEST"):
        build_container(build_module_graph(AppModule))


def test_special_request_token_resolves_within_request_scope(build_request: RequestFactory) -> None:
    @Injectable(scope="request")
    class RequestAwareService:
        def __init__(self, request: Annotated[object, Inject(REQUEST)]) -> None:
            self.request = request

    @Module(providers=[RequestAwareService], exports=[RequestAwareService])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    request = build_request(path="/request-aware")

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
