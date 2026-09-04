"""Integration tests that a request identity cannot cross request boundaries."""

from __future__ import annotations

from typing import Any, cast

import pytest
from starlette.requests import Request
from starlette.testclient import TestClient

from bustan import Controller, create_app, Get, Injectable, Module, Scope
from bustan.core.errors import InvalidControllerError, ProviderResolutionError


def test_default_scope_controller_cannot_hold_a_request_scoped_provider() -> None:
    @Injectable(scope=Scope.REQUEST)
    class CurrentUser:
        def __init__(self, request: Request) -> None:
            self.name = request.headers.get("x-user", "anonymous")

    @Controller("/whoami")
    class WhoAmIController:
        def __init__(self, current_user: CurrentUser) -> None:
            self.current_user = current_user

        @Get()
        async def whoami(self) -> dict[str, str]:
            return {"user": self.current_user.name}

    @Module(controllers=[WhoAmIController], providers=[CurrentUser])
    class AppModule:
        pass

    with pytest.raises(ProviderResolutionError, match="request-scoped provider"):
        create_app(AppModule)


def test_request_scoped_controller_serves_each_caller_their_own_identity() -> None:
    @Injectable(scope=Scope.REQUEST)
    class CurrentUser:
        def __init__(self, request: Request) -> None:
            self.name = request.headers.get("x-user", "anonymous")

    @Controller("/whoami", scope=Scope.REQUEST)
    class WhoAmIController:
        def __init__(self, current_user: CurrentUser) -> None:
            self.current_user = current_user

        @Get()
        async def whoami(self) -> dict[str, str]:
            return {"user": self.current_user.name}

    @Module(controllers=[WhoAmIController], providers=[CurrentUser])
    class AppModule:
        pass

    with TestClient(cast(Any, create_app(AppModule))) as client:
        first = client.get("/whoami", headers={"x-user": "alice"})
        second = client.get("/whoami", headers={"x-user": "bob"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == {"user": "alice"}
    assert second.json() == {"user": "bob"}


def test_singleton_controller_cannot_hold_a_durable_provider() -> None:
    @Injectable(scope=Scope.DURABLE)
    class TenantCache:
        @classmethod
        def get_durable_context_key(cls, request: Request | None) -> str:
            return "none" if request is None else request.headers.get("x-tenant", "unknown")

    @Controller("/tenant")
    class TenantController:
        def __init__(self, cache: TenantCache) -> None:
            self.cache = cache

        @Get()
        async def read(self) -> dict[str, bool]:
            return {"ok": True}

    @Module(controllers=[TenantController], providers=[TenantCache])
    class AppModule:
        pass

    with pytest.raises(ProviderResolutionError, match="durable-scoped provider"):
        create_app(AppModule)


def test_transient_controller_keeps_its_own_durable_partition() -> None:
    @Injectable(scope=Scope.DURABLE)
    class TenantCache:
        @classmethod
        def get_durable_context_key(cls, request: Request | None) -> str:
            return "none" if request is None else request.headers.get("x-tenant", "unknown")

        def __init__(self) -> None:
            self.tenant = "unset"

    @Controller("/tenant", scope=Scope.TRANSIENT)
    class TenantController:
        def __init__(self, cache: TenantCache) -> None:
            self.cache = cache

        @Get()
        async def read(self) -> dict[str, int]:
            return {"cache": id(self.cache)}

    @Module(controllers=[TenantController], providers=[TenantCache])
    class AppModule:
        pass

    with TestClient(cast(Any, create_app(AppModule))) as client:
        acme = client.get("/tenant", headers={"x-tenant": "acme"})
        acme_again = client.get("/tenant", headers={"x-tenant": "acme"})
        globex = client.get("/tenant", headers={"x-tenant": "globex"})

    assert acme.json()["cache"] == acme_again.json()["cache"]
    assert acme.json()["cache"] != globex.json()["cache"]


def test_durable_provider_cannot_retain_the_first_callers_request() -> None:
    @Injectable(scope=Scope.DURABLE)
    class TenantSession:
        @classmethod
        def get_durable_context_key(cls, request: Request | None) -> str:
            return "none" if request is None else request.headers.get("x-tenant", "unknown")

        def __init__(self, request: Request) -> None:
            self.retained_request = request

    @Controller("/session", scope=Scope.REQUEST)
    class SessionController:
        def __init__(self, session: TenantSession) -> None:
            self.session = session

        @Get()
        async def read(self) -> dict[str, str]:
            return {"path": self.session.retained_request.url.path}

    @Module(controllers=[SessionController], providers=[TenantSession])
    class AppModule:
        pass

    with pytest.raises(ProviderResolutionError, match="framework-owned type Request"):
        create_app(AppModule)


def test_durable_scoped_controller_is_refused_with_a_clear_message() -> None:
    @Controller("/tenant", scope=Scope.DURABLE)
    class TenantController:
        @Get()
        async def read(self) -> dict[str, bool]:
            return {"ok": True}

    @Module(controllers=[TenantController])
    class AppModule:
        pass

    with pytest.raises(InvalidControllerError, match="durable scope"):
        create_app(AppModule)


def test_singleton_controller_cannot_reach_request_state_through_a_transient() -> None:
    @Injectable(scope=Scope.REQUEST)
    class CurrentUser:
        def __init__(self, request: Request) -> None:
            self.name = request.headers.get("x-user", "anonymous")

    @Injectable(scope=Scope.TRANSIENT)
    class UserHolder:
        def __init__(self, current_user: CurrentUser) -> None:
            self.current_user = current_user

    @Controller("/whoami")
    class WhoAmIController:
        def __init__(self, holder: UserHolder) -> None:
            self.holder = holder

        @Get()
        async def whoami(self) -> dict[str, str]:
            return {"user": self.holder.current_user.name}

    @Module(controllers=[WhoAmIController], providers=[CurrentUser, UserHolder])
    class AppModule:
        pass

    with pytest.raises(ProviderResolutionError, match="reaches request-scoped state"):
        create_app(AppModule)


def test_singleton_controller_cannot_reach_request_state_through_an_alias() -> None:
    class AuditPort:
        name: str

    @Injectable(scope=Scope.REQUEST)
    class RequestAudit(AuditPort):
        def __init__(self, request: Request) -> None:
            self.name = request.headers.get("x-user", "anonymous")

    @Controller("/audit")
    class AuditController:
        def __init__(self, audit: AuditPort) -> None:
            self.audit = audit

        @Get()
        async def read(self) -> dict[str, str]:
            return {"user": self.audit.name}

    @Module(
        controllers=[AuditController],
        providers=[RequestAudit, {"provide": AuditPort, "use_existing": RequestAudit}],
    )
    class AppModule:
        pass

    with pytest.raises(ProviderResolutionError, match="reaches request-scoped state"):
        create_app(AppModule)


def test_singleton_factory_cannot_inject_a_request_scoped_provider() -> None:
    @Injectable(scope=Scope.REQUEST)
    class CurrentUser:
        def __init__(self, request: Request) -> None:
            self.name = request.headers.get("x-user", "anonymous")

    class Snapshot:
        def __init__(self, name: str) -> None:
            self.name = name

    def build_snapshot(current_user: CurrentUser) -> Snapshot:
        return Snapshot(current_user.name)

    @Controller("/snapshot", scope=Scope.REQUEST)
    class SnapshotController:
        def __init__(self, snapshot: Snapshot) -> None:
            self.snapshot = snapshot

        @Get()
        async def read(self) -> dict[str, str]:
            return {"user": self.snapshot.name}

    @Module(
        controllers=[SnapshotController],
        providers=[
            CurrentUser,
            {"provide": Snapshot, "use_factory": build_snapshot, "inject": [CurrentUser]},
        ],
    )
    class AppModule:
        pass

    with pytest.raises(ProviderResolutionError, match="request-scoped provider"):
        create_app(AppModule, _no_lifespan=True)


def test_a_transient_that_reaches_only_singletons_is_still_injectable() -> None:
    @Injectable
    class BillingService:
        def read_plan(self) -> str:
            return "pro"

    @Injectable(scope=Scope.TRANSIENT)
    class BillingHelper:
        def __init__(self, billing: BillingService) -> None:
            self.billing = billing

    @Controller("/plan")
    class PlanController:
        def __init__(self, helper: BillingHelper) -> None:
            self.helper = helper

        @Get()
        async def read(self) -> dict[str, str]:
            return {"plan": self.helper.billing.read_plan()}

    @Module(controllers=[PlanController], providers=[BillingService, BillingHelper])
    class AppModule:
        pass

    with TestClient(cast(Any, create_app(AppModule))) as client:
        response = client.get("/plan")

    assert response.status_code == 200
    assert response.json() == {"plan": "pro"}
