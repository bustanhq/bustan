"""Integration tests for compiled route policy plans."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from bustan import Controller, Get, Module, SkipThrottle, create_app
from bustan.platform.http.abstractions import HttpRequest
from bustan.security import AUTHENTICATOR_REGISTRY, Auth, RateLimit, Roles
from starlette.testclient import TestClient


@dataclass(frozen=True, slots=True)
class PrincipalStub:
    id: str
    roles: tuple[str, ...]
    permissions: tuple[str, ...]


class AuthenticatorStub:
    def __init__(self, principal: PrincipalStub | None) -> None:
        self._principal = principal

    async def authenticate(self, context) -> PrincipalStub | None:
        return self._principal


def test_create_app_attaches_compiled_policy_plans_to_routes() -> None:
    @Auth("jwt")
    @Roles("admin")
    @RateLimit(limit=5, window="1m")
    @Controller("/secure")
    class SecureController:
        @SkipThrottle
        @Get("/")
        def read_secure(self) -> dict[str, str]:
            return {"status": "ok"}

    @Module(controllers=[SecureController])
    class AppModule:
        pass

    application = create_app(AppModule)
    starlette_app = application.get_http_adapter().get_instance()
    route = next(route for route in starlette_app.routes if getattr(route, "path", None) == "/secure")
    contract = getattr(route, "bustan_route_contract")

    assert contract.policy_plan.auth is not None
    assert contract.policy_plan.auth.strategy == "jwt"
    assert contract.policy_plan.roles == ("admin",)
    assert contract.policy_plan.rate_limit is not None
    assert contract.policy_plan.rate_limit.limit == 5
    assert contract.policy_plan.rate_limit.skip is True


def test_create_app_binds_authenticated_principals_for_policy_guard_protected_routes() -> None:
    @Auth("jwt")
    @Roles("admin")
    @Controller("/secure")
    class SecureController:
        @Get("/")
        def read_secure(self, request: HttpRequest) -> dict[str, str]:
            principal = request.state.principal
            return {"principal_id": principal.id}

    @Module(
        controllers=[SecureController],
        providers=[
            {
                "provide": AUTHENTICATOR_REGISTRY,
                "use_value": {
                    "jwt": AuthenticatorStub(
                        PrincipalStub(
                            id="user-1",
                            roles=("admin",),
                            permissions=("users:read",),
                        )
                    )
                },
            }
        ],
    )
    class AppModule:
        pass

    application = create_app(AppModule)
    with TestClient(cast(Any, application)) as client:
        response = client.get("/secure")

    assert response.status_code == 200
    assert response.json() == {"principal_id": "user-1"}


def test_create_app_returns_deterministic_policy_denial_responses() -> None:
    @Auth("jwt")
    @Roles("admin")
    @Controller("/secure")
    class SecureController:
        @Get("/")
        def read_secure(self) -> dict[str, str]:
            return {"status": "ok"}

    @Module(
        controllers=[SecureController],
        providers=[
            {
                "provide": AUTHENTICATOR_REGISTRY,
                "use_value": {
                    "jwt": AuthenticatorStub(
                        PrincipalStub(
                            id="user-1",
                            roles=("user",),
                            permissions=("users:read",),
                        )
                    )
                },
            }
        ],
    )
    class AppModule:
        pass

    application = create_app(AppModule)
    with TestClient(cast(Any, application)) as client:
        response = client.get("/secure")

    assert response.status_code == 403
    assert response.json()["detail"] == "Policy denied: missing roles ('admin',)"