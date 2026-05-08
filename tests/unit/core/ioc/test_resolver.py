"""Unit tests for resolver helper branches and special-token handling."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response

from bustan.common.decorators.injectable import Inject, Optional
from bustan.common.types import ProviderScope
from bustan.core.errors import ProviderResolutionError
from bustan.core.ioc.overrides import OverrideManager
from bustan.core.ioc.registry import Binding, Registry
from bustan.core.ioc.resolver import ParsedDependency, ResolutionFrame, Resolver
from bustan.core.ioc.scopes import ScopeManager
from bustan.core.ioc.tokens import APPLICATION, INQUIRER, REQUEST, RESPONSE

if TYPE_CHECKING:
    class MissingType:
        pass


class AppModule:
    pass


class MissingDependency:
    pass


def test_resolver_special_tokens_cover_runtime_success_and_error_paths() -> None:
    resolver, _registry = _resolver()
    request = _build_request("/runtime")
    application = Starlette()
    request_with_app = _build_request("/runtime", app=application)
    response = Response("ok")

    response_token = resolver.scope_manager.push_response(response)
    application_token = resolver.scope_manager.push_application(application)
    try:
        assert resolver._resolve_special_token(
            ParsedDependency(annotation=object, token=REQUEST, optional=False),
            class_cls=Service,
            parameter_name="request",
            active_request=request,
            owner_is_controller=True,
            is_request_scoped=False,
            is_durable_scoped=False,
        ) is request
        assert resolver._resolve_special_token(
            ParsedDependency(annotation=object, token=RESPONSE, optional=False),
            class_cls=Service,
            parameter_name="response",
            active_request=request,
            owner_is_controller=False,
            is_request_scoped=False,
            is_durable_scoped=False,
        ) is response
        assert resolver._resolve_special_token(
            ParsedDependency(annotation=object, token=APPLICATION, optional=False),
            class_cls=Service,
            parameter_name="application",
            active_request=request,
            owner_is_controller=False,
            is_request_scoped=False,
            is_durable_scoped=False,
        ) is application
    finally:
        resolver.scope_manager.pop_application(application_token)
        resolver.scope_manager.pop_response(response_token)

    assert resolver._resolve_special_token(
        ParsedDependency(annotation=object, token=APPLICATION, optional=False),
        class_cls=Service,
        parameter_name="application",
        active_request=request_with_app,
        owner_is_controller=False,
        is_request_scoped=False,
        is_durable_scoped=False,
    ) is application

    with pytest.raises(ProviderResolutionError, match="requested REQUEST"):
        resolver._resolve_special_token(
            ParsedDependency(annotation=object, token=REQUEST, optional=False),
            class_cls=Service,
            parameter_name="request",
            active_request=None,
            owner_is_controller=False,
            is_request_scoped=False,
            is_durable_scoped=False,
        )

    with pytest.raises(ProviderResolutionError, match="framework-owned type Request"):
        resolver._resolve_special_token(
            ParsedDependency(annotation=Request, token=Request, optional=False),
            class_cls=Service,
            parameter_name="request",
            active_request=None,
            owner_is_controller=False,
            is_request_scoped=False,
            is_durable_scoped=False,
        )

    with pytest.raises(ProviderResolutionError, match="requested RESPONSE"):
        resolver._resolve_special_token(
            ParsedDependency(annotation=object, token=RESPONSE, optional=False),
            class_cls=Service,
            parameter_name="response",
            active_request=None,
            owner_is_controller=False,
            is_request_scoped=False,
            is_durable_scoped=False,
        )

    with pytest.raises(ProviderResolutionError, match="framework-owned type Starlette"):
        resolver._resolve_special_token(
            ParsedDependency(annotation=Starlette, token=Starlette, optional=False),
            class_cls=Service,
            parameter_name="app",
            active_request=None,
            owner_is_controller=False,
            is_request_scoped=False,
            is_durable_scoped=False,
        )

    with pytest.raises(ProviderResolutionError, match="requested APPLICATION"):
        resolver._resolve_special_token(
            ParsedDependency(annotation=object, token=APPLICATION, optional=False),
            class_cls=Service,
            parameter_name="app",
            active_request=None,
            owner_is_controller=False,
            is_request_scoped=False,
            is_durable_scoped=False,
        )

    with pytest.raises(ProviderResolutionError, match="requested INQUIRER"):
        resolver._resolve_special_token(
            ParsedDependency(annotation=object, token=INQUIRER, optional=False),
            class_cls=Service,
            parameter_name="inquirer",
            active_request=None,
            owner_is_controller=False,
            is_request_scoped=False,
            is_durable_scoped=False,
        )

    stack_token = resolver.resolution_stack.set((ResolutionFrame("ParentService", AppModule),))
    try:
        assert (
            resolver._resolve_special_token(
                ParsedDependency(annotation=object, token=INQUIRER, optional=False),
                class_cls=Service,
                parameter_name="inquirer",
                active_request=None,
                owner_is_controller=False,
                is_request_scoped=False,
                is_durable_scoped=False,
            )
            == "ParentService"
        )
    finally:
        resolver.resolution_stack.reset(stack_token)


def test_resolver_cache_helpers_cover_request_durable_singleton_and_transient_paths() -> None:
    resolver, _registry = _resolver()
    request = _build_request("/cache")
    request_binding = _binding("request-token", ProviderScope.REQUEST)
    durable_binding = _binding("durable-token", ProviderScope.DURABLE)
    singleton_binding = _binding("singleton-token", ProviderScope.SINGLETON)
    transient_binding = _binding("transient-token", ProviderScope.TRANSIENT)

    with pytest.raises(ProviderResolutionError, match="requires an active request"):
        resolver._get_cached_instance(
            request_binding,
            (AppModule, "request-token"),
            AppModule,
            "request-token",
        )

    request_token = resolver.scope_manager.push_request(request)
    try:
        request_cache_key = (AppModule, "request-token")
        resolver.scope_manager.get_request_cache(request)[request_cache_key] = "cached-request"
        assert resolver._get_cached_instance(
            request_binding,
            request_cache_key,
            AppModule,
            "request-token",
        ) == "cached-request"
        assert resolver._cache_instance(
            request_binding,
            request_cache_key,
            AppModule,
            "request-token",
            "new-request",
        ) == "new-request"

        durable_cache_key = (AppModule, "durable-token")
        assert resolver._get_cached_instance(
            durable_binding,
            durable_cache_key,
            AppModule,
            "durable-token",
        ) is None
        first_durable = object()
        second_durable = object()
        assert (
            resolver._cache_instance(
                durable_binding,
                durable_cache_key,
                AppModule,
                "durable-token",
                first_durable,
            )
            is first_durable
        )
        assert (
            resolver._cache_instance(
                durable_binding,
                durable_cache_key,
                AppModule,
                "durable-token",
                second_durable,
            )
            is first_durable
        )
    finally:
        resolver.scope_manager.pop_request(request_token)

    singleton_cache_key = (AppModule, "singleton-token")
    assert resolver._get_cached_instance(
        singleton_binding,
        singleton_cache_key,
        AppModule,
        "singleton-token",
    ) is None
    first_singleton = object()
    second_singleton = object()
    assert (
        resolver._cache_instance(
            singleton_binding,
            singleton_cache_key,
            AppModule,
            "singleton-token",
            first_singleton,
        )
        is first_singleton
    )
    assert (
        resolver._cache_instance(
            singleton_binding,
            singleton_cache_key,
            AppModule,
            "singleton-token",
            second_singleton,
        )
        is first_singleton
    )
    assert resolver._get_cached_instance(
        singleton_binding,
        singleton_cache_key,
        AppModule,
        "singleton-token",
    ) is first_singleton

    transient_cache_key = (AppModule, "transient-token")
    transient_instance = object()
    assert resolver._get_cached_instance(
        transient_binding,
        transient_cache_key,
        AppModule,
        "transient-token",
    ) is None
    assert (
        resolver._cache_instance(
            transient_binding,
            transient_cache_key,
            AppModule,
            "transient-token",
            transient_instance,
        )
        is transient_instance
    )


@pytest.mark.anyio
async def test_resolver_factory_helpers_cover_sync_async_and_binding_flags() -> None:
    resolver, registry = _resolver()

    class Config:
        pass

    config = Config()
    registry.register_binding(
        (AppModule, Config),
        Binding(Config, AppModule, "value", config, ProviderScope.SINGLETON),
    )
    registry.set_visibility(AppModule, {Config: AppModule})

    def build_client(current_config: Config) -> str:
        return current_config.__class__.__name__

    class AwaitableResult:
        def __await__(self):
            async def _value():
                return "Config"

            return _value().__await__()

    def build_client_awaitable(current_config: Config) -> object:
        return AwaitableResult()

    async def build_client_async(current_config: Config) -> str:
        return current_config.__class__.__name__

    assert resolver.call_factory(build_client, (Config,), module=AppModule) == "Config"
    with pytest.raises(ProviderResolutionError, match="returned an awaitable"):
        resolver.call_factory(build_client_awaitable, (Config,), module=AppModule)

    assert await resolver.call_factory_async(build_client_async, (Config,), module=AppModule) == "Config"
    assert resolver._binding_requires_async(
        Binding("sync", AppModule, "value", object(), ProviderScope.SINGLETON)
    ) is False
    assert resolver._binding_requires_async(
        Binding(
            "async",
            AppModule,
            "factory",
            (build_client_async, (Config,)),
            ProviderScope.SINGLETON,
        )
    ) is True


def test_resolver_constructor_dependencies_cover_optional_inject_keywords_and_errors() -> None:
    resolver, registry = _resolver()
    provided = object()
    registry.register_binding(
        (AppModule, "provided"),
        Binding("provided", AppModule, "value", provided, ProviderScope.SINGLETON),
    )
    registry.set_visibility(AppModule, {"provided": AppModule})

    class Consumer:
        def __init__(
            self,
            maybe: Annotated[MissingDependency, Optional()],
            value: Annotated[object, Inject("provided")],
            *,
            named: Annotated[object, Inject("provided")],
        ) -> None:
            self.maybe = maybe
            self.value = value
            self.named = named

    positional_arguments, keyword_arguments = resolver._resolve_constructor_dependencies(
        Consumer,
        AppModule,
    )

    assert positional_arguments == (None, provided)
    assert keyword_arguments == {"named": provided}

    class MissingAnnotation:
        def __init__(self, dependency) -> None:
            self.dependency = dependency

    with pytest.raises(ProviderResolutionError, match="missing a type annotation"):
        resolver._resolve_constructor_dependencies(MissingAnnotation, AppModule)

    class VariadicConsumer:
        def __init__(self, *dependencies: int) -> None:
            self.dependencies = dependencies

    with pytest.raises(ProviderResolutionError, match="unsupported variadic parameter"):
        resolver._resolve_constructor_dependencies(VariadicConsumer, AppModule)

    class UnresolvedDependencyConsumer:
        def __init__(self, dependency: MissingType) -> None:
            self.dependency = dependency

    with pytest.raises(ProviderResolutionError, match="Could not resolve type hints"):
        resolver._resolve_constructor_dependencies(UnresolvedDependencyConsumer, AppModule)


def _resolver() -> tuple[Resolver, Registry]:
    registry = Registry()
    registry.set_visibility(AppModule, {})
    return Resolver(registry, ScopeManager(), OverrideManager(registry)), registry


def _binding(token: object, scope: ProviderScope) -> Binding:
    return Binding(token, AppModule, "value", object(), scope)


def _build_request(path: str, *, app: Starlette | None = None) -> Request:
    scope: dict[str, object] = {
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
    if app is not None:
        scope["app"] = app

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(scope, receive)


class Service:
    pass
