"""Regression tests for resolver seam bugs: INQUIRER, overrides, cycles, scopes."""

from __future__ import annotations

import threading
from typing import Annotated, Any, cast

import anyio
import pytest
from starlette.requests import Request

from bustan import Injectable, Module, Scope
from bustan.common.decorators.injectable import Inject
from bustan.core.errors import ProviderResolutionError
from bustan.core.ioc.container import build_container
from bustan.core.ioc.tokens import INQUIRER
from bustan.core.module.graph import build_module_graph


def test_inquirer_receives_the_dependent_class_during_nested_resolution() -> None:
    @Injectable
    class AuditTrail:
        def __init__(self, inquirer: Annotated[object, Inject(INQUIRER)]) -> None:
            self.inquirer = inquirer

    @Injectable
    class BillingService:
        def __init__(self, audit_trail: AuditTrail) -> None:
            self.audit_trail = audit_trail

    @Module(providers=[AuditTrail, BillingService], exports=[BillingService])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    billing = cast(Any, container.resolve(BillingService, module=AppModule))

    assert billing.audit_trail.inquirer is BillingService


def test_inquirer_receives_the_class_passed_to_instantiate_class() -> None:
    @Injectable(scope=Scope.TRANSIENT)
    class AuditTrail:
        def __init__(self, inquirer: Annotated[object, Inject(INQUIRER)]) -> None:
            self.inquirer = inquirer

    class StandaloneConsumer:
        def __init__(self, audit_trail: AuditTrail) -> None:
            self.audit_trail = audit_trail

    @Module(providers=[AuditTrail], exports=[AuditTrail])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    consumer = cast(
        Any, container.instantiate_class(StandaloneConsumer, module=AppModule)
    )

    assert consumer.audit_trail.inquirer is StandaloneConsumer


def test_override_of_exported_provider_applies_through_importing_modules() -> None:
    @Injectable
    class UserService:
        pass

    @Module(providers=[UserService], exports=[UserService])
    class UsersModule:
        pass

    @Module(imports=[UsersModule])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    replacement = object()
    container.override(UserService, replacement)

    assert container.resolve(UserService, module=AppModule) is replacement
    assert container.resolve(UserService, module=UsersModule) is replacement


def test_same_token_name_in_two_modules_is_not_reported_as_a_cycle() -> None:
    @Injectable
    class Svc:
        def __init__(self, cfg: Annotated[object, Inject("cfg")]) -> None:
            self.cfg = cfg

    @Module(
        providers=[Svc, {"provide": "cfg", "use_value": "inner-config"}],
        exports=[Svc],
    )
    class InnerModule:
        pass

    @Injectable
    class CfgHolder:
        def __init__(self, svc: Svc) -> None:
            self.svc = svc

    @Module(
        imports=[InnerModule],
        providers=[{"provide": "cfg", "use_class": CfgHolder}],
        exports=["cfg"],
    )
    class OuterModule:
        pass

    container = build_container(build_module_graph(OuterModule))
    holder = cast(Any, container.resolve("cfg", module=OuterModule))

    assert isinstance(holder, CfgHolder)
    assert holder.svc.cfg == "inner-config"


def test_class_bound_in_two_modules_uses_the_scope_of_the_resolved_binding() -> None:
    class Shared:
        def __init__(self, request: Request) -> None:
            self.request = request

    @Module(
        providers=[{"provide": "req_scoped", "use_class": Shared, "scope": "request"}],
        exports=["req_scoped"],
    )
    class RequestModule:
        pass

    @Module(
        imports=[RequestModule],
        providers=[{"provide": "singleton_bound", "use_class": Shared, "scope": "singleton"}],
    )
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    request = _build_request("/shared")

    resolved = cast(
        Any,
        container.resolve("req_scoped", module=RequestModule, request=request),
    )
    assert resolved.request is request

    with pytest.raises(ProviderResolutionError, match="framework-owned type Request"):
        container.resolve("singleton_bound", module=AppModule)


def test_concurrent_resolution_constructs_a_singleton_exactly_once() -> None:
    constructions: list[int] = []
    release = threading.Event()

    @Injectable
    class SlowService:
        def __init__(self) -> None:
            constructions.append(1)
            release.wait(timeout=1)

    @Module(providers=[SlowService], exports=[SlowService])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    resolved: list[object] = []
    threads = [
        threading.Thread(
            target=lambda: resolved.append(container.resolve(SlowService, module=AppModule))
        )
        for _ in range(4)
    ]
    for thread in threads:
        thread.start()
    release.set()
    for thread in threads:
        thread.join(timeout=5)

    assert len(constructions) == 1
    assert len(resolved) == 4
    assert all(instance is resolved[0] for instance in resolved)


def test_resolve_async_supports_class_providers_with_async_factory_dependencies() -> None:
    async def make_connection() -> str:
        return "connected"

    @Injectable
    class NeedsConnection:
        def __init__(self, conn: Annotated[str, Inject("conn")]) -> None:
            self.conn = conn

    @Module(
        providers=[
            NeedsConnection,
            {"provide": "conn", "use_factory": make_connection, "scope": "transient"},
        ],
        exports=[NeedsConnection],
    )
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))

    async def resolve() -> object:
        return await container.resolve_async(NeedsConnection, module=AppModule)

    instance = cast(Any, anyio.run(resolve))
    assert instance.conn == "connected"


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
