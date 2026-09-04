"""Unit tests for the rules that keep one caller's state out of another's."""

from __future__ import annotations

import pytest
from starlette.requests import Request

from bustan import Injectable, Module, Scope
from bustan.common.constants import BUSTAN_PROVIDER_ATTR
from bustan.core.errors import InvalidProviderError, ProviderResolutionError
from bustan.core.ioc.container import build_container
from bustan.core.ioc.registry import normalize_provider
from bustan.core.module.graph import build_module_graph


def test_use_class_dict_inherits_the_target_class_scope() -> None:
    class AuditPort:
        pass

    @Injectable(scope=Scope.REQUEST)
    class RequestAudit(AuditPort):
        pass

    @Module(providers=[{"provide": AuditPort, "use_class": RequestAudit}])
    class AppModule:
        pass

    binding = normalize_provider({"provide": AuditPort, "use_class": RequestAudit}, AppModule)

    assert getattr(RequestAudit, BUSTAN_PROVIDER_ATTR)["scope"] is Scope.REQUEST
    assert binding.scope is Scope.REQUEST


def test_use_class_dict_may_narrow_the_declared_scope() -> None:
    class AuditPort:
        pass

    @Injectable(scope=Scope.REQUEST)
    class RequestAudit(AuditPort):
        pass

    @Module(providers=[])
    class AppModule:
        pass

    binding = normalize_provider(
        {"provide": AuditPort, "use_class": RequestAudit, "scope": Scope.TRANSIENT}, AppModule
    )

    assert binding.scope is Scope.TRANSIENT


def test_use_class_dict_may_not_widen_the_declared_scope() -> None:
    class AuditPort:
        pass

    @Injectable(scope=Scope.REQUEST)
    class RequestAudit(AuditPort):
        pass

    @Module(providers=[])
    class AppModule:
        pass

    with pytest.raises(InvalidProviderError, match="never widen it"):
        normalize_provider(
            {"provide": AuditPort, "use_class": RequestAudit, "scope": Scope.SINGLETON},
            AppModule,
        )


def test_use_class_dict_defaults_to_singleton_for_an_undeclared_class() -> None:
    class AuditPort:
        pass

    class PlainAudit(AuditPort):
        pass

    @Module(providers=[])
    class AppModule:
        pass

    binding = normalize_provider({"provide": AuditPort, "use_class": PlainAudit}, AppModule)

    assert binding.scope is Scope.SINGLETON


def test_singleton_provider_cannot_hold_a_durable_provider() -> None:
    @Injectable(scope=Scope.DURABLE)
    class TenantCache:
        @classmethod
        def get_durable_context_key(cls, request: Request | None) -> str:
            return "tenant"

    @Injectable
    class ReportService:
        def __init__(self, cache: TenantCache) -> None:
            self.cache = cache

    @Module(providers=[TenantCache, ReportService])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))

    with pytest.raises(ProviderResolutionError, match="durable-scoped provider"):
        container.resolve(ReportService, module=AppModule)


def test_request_scoped_provider_may_hold_a_durable_provider() -> None:
    @Injectable(scope=Scope.DURABLE)
    class TenantCache:
        @classmethod
        def get_durable_context_key(cls, request: Request | None) -> str:
            assert request is not None
            return request.headers["x-tenant-id"]

    @Injectable(scope=Scope.REQUEST)
    class TenantReport:
        def __init__(self, cache: TenantCache) -> None:
            self.cache = cache

    @Module(providers=[TenantCache, TenantReport])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    request = _build_request("/reports", headers=[(b"x-tenant-id", b"acme")])

    report = container.resolve(TenantReport, module=AppModule, request=request)

    assert isinstance(report, TenantReport)


def test_durable_provider_cannot_inject_the_request() -> None:
    @Injectable(scope=Scope.DURABLE)
    class TenantSession:
        @classmethod
        def get_durable_context_key(cls, request: Request | None) -> str:
            assert request is not None
            return request.headers["x-tenant-id"]

        def __init__(self, request: Request) -> None:
            self.request = request

    @Module(providers=[TenantSession])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    request = _build_request("/session", headers=[(b"x-tenant-id", b"acme")])

    with pytest.raises(ProviderResolutionError, match="framework-owned type Request"):
        container.resolve(TenantSession, module=AppModule, request=request)


def test_instantiate_class_denies_request_scope_when_no_owner_scope_is_given() -> None:
    @Injectable(scope=Scope.REQUEST)
    class RequestState:
        def __init__(self, request: Request) -> None:
            self.request = request

    class Consumer:
        def __init__(self, request_state: RequestState) -> None:
            self.request_state = request_state

    @Module(providers=[RequestState])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    request = _build_request("/consume", headers=[])

    with pytest.raises(ProviderResolutionError, match="request-scoped provider"):
        container.instantiate_class(Consumer, module=AppModule, request=request)


def test_instantiate_class_honours_an_explicit_owner_scope() -> None:
    @Injectable(scope=Scope.REQUEST)
    class RequestState:
        def __init__(self, request: Request) -> None:
            self.request = request

    class Consumer:
        def __init__(self, request_state: RequestState) -> None:
            self.request_state = request_state

    @Module(providers=[RequestState])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    request = _build_request("/consume", headers=[])

    consumer = container.resolver.instantiate_class(
        Consumer, module=AppModule, request=request, owner_scope=Scope.REQUEST
    )

    assert isinstance(consumer, Consumer)


def _build_request(path: str, *, headers: list[tuple[bytes, bytes]]) -> Request:
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": b"",
        "headers": [(b"host", b"testserver"), *headers],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
        "path_params": {},
    }

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(scope, receive)
