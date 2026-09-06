"""Integration tests for controllers that ask for a durable lifetime."""

from __future__ import annotations

from typing import Any, cast

import pytest
from starlette.requests import Request
from starlette.testclient import TestClient

from bustan import Controller, Get, Injectable, Module, Scope, create_app
from bustan.kernel.errors import InvalidControllerError


def test_durable_controller_without_a_context_key_hook_is_refused_before_it_serves() -> None:
    @Controller("/tenants", scope=Scope.DURABLE)
    class TenantsController:
        @Get("/")
        def read_tenant(self) -> dict[str, int]:
            return {"instance": id(self)}

    @Module(controllers=[TenantsController])
    class AppModule:
        pass

    with pytest.raises(InvalidControllerError):
        create_app(AppModule)


def test_durable_controller_with_a_context_key_hook_is_refused_before_it_serves() -> None:
    @Controller("/tenants", scope=Scope.DURABLE)
    class TenantsController:
        @classmethod
        def get_durable_context_key(cls, request: Request | None) -> str:
            return request.headers.get("x-tenant", "none") if request is not None else "none"

        @Get("/")
        def read_tenant(self) -> dict[str, int]:
            return {"instance": id(self)}

    @Module(controllers=[TenantsController])
    class AppModule:
        pass

    with pytest.raises(InvalidControllerError):
        create_app(AppModule)


def test_per_tenant_state_is_served_by_a_durable_provider_the_controller_injects() -> None:
    @Injectable(scope=Scope.DURABLE)
    class TenantContext:
        @classmethod
        def get_durable_context_key(cls, request: Request | None) -> str:
            return request.headers.get("x-tenant", "none") if request is not None else "none"

    @Controller("/tenants", scope=Scope.REQUEST)
    class TenantsController:
        def __init__(self, tenant_context: TenantContext) -> None:
            self.tenant_context = tenant_context

        @Get("/")
        def read_tenant(self) -> dict[str, int]:
            return {"tenant_context": id(self.tenant_context)}

    @Module(controllers=[TenantsController], providers=[TenantContext])
    class AppModule:
        pass

    with TestClient(cast(Any, create_app(AppModule))) as client:
        contexts = [
            client.get("/tenants/", headers={"x-tenant": f"tenant-{index}"}).json()[
                "tenant_context"
            ]
            for index in range(4)
        ]
        repeated = client.get("/tenants/", headers={"x-tenant": "tenant-0"}).json()[
            "tenant_context"
        ]

    assert len(set(contexts)) == 4
    assert repeated == contexts[0]
