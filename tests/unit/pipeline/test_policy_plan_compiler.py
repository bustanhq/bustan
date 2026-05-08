"""Unit tests for compiled route policy plans."""

from __future__ import annotations

from bustan import Controller, Get, Module, SkipThrottle
from bustan.core.ioc.container import build_container
from bustan.core.module.graph import build_module_graph
from bustan.platform.http.compiler import compile_route_contracts
from bustan.security import Audit, Auth, Cache, DeprecatedRoute, Idempotent, Owner, Permissions, Public, RateLimit, Roles


def test_each_policy_decorator_family_contributes_to_one_compiled_plan() -> None:
    @Auth("jwt")
    @Roles("admin")
    @Permissions("users:read")
    @RateLimit(limit=100, window="1m")
    @Cache(ttl=60)
    @Idempotent(key_header="Idempotency-Key")
    @Audit(event="user.read")
    @Owner("identity-platform")
    @Controller("/users")
    class UsersController:
        @Public()
        @DeprecatedRoute(sunset="2026-12-31", replacement="/v2/users")
        @SkipThrottle
        @Get("/")
        def list_users(self) -> dict[str, str]:
            return {"status": "ok"}

    @Module(controllers=[UsersController])
    class AppModule:
        pass

    graph = build_module_graph(AppModule)
    container = build_container(graph)

    [contract] = compile_route_contracts(graph, container)

    assert contract.policy_plan.auth is not None
    assert contract.policy_plan.auth.strategy == "jwt"
    assert contract.policy_plan.public is True
    assert contract.policy_plan.roles == ("admin",)
    assert contract.policy_plan.permissions == ("users:read",)
    assert contract.policy_plan.rate_limit is not None
    assert contract.policy_plan.rate_limit.limit == 100
    assert contract.policy_plan.rate_limit.window == "1m"
    assert contract.policy_plan.rate_limit.skip is True
    assert contract.policy_plan.cache is not None
    assert contract.policy_plan.cache.ttl == 60
    assert contract.policy_plan.idempotency is not None
    assert contract.policy_plan.idempotency.key_header == "Idempotency-Key"
    assert contract.policy_plan.audit is not None
    assert contract.policy_plan.audit.event == "user.read"
    assert contract.policy_plan.owner == "identity-platform"
    assert contract.policy_plan.deprecation is not None
    assert contract.policy_plan.deprecation.replacement == "/v2/users"


def test_route_and_controller_policies_merge_deterministically() -> None:
    @Roles("admin")
    @Permissions("users:read")
    @Owner("identity-platform")
    @Controller("/users")
    class UsersController:
        @Roles("manager")
        @Permissions("users:write")
        @Owner("accounts-platform")
        @Get("/")
        def list_users(self) -> dict[str, str]:
            return {"status": "ok"}

    @Module(controllers=[UsersController])
    class AppModule:
        pass

    graph = build_module_graph(AppModule)
    container = build_container(graph)

    [contract] = compile_route_contracts(graph, container)

    assert contract.policy_plan.roles == ("admin", "manager")
    assert contract.policy_plan.permissions == ("users:read", "users:write")
    assert contract.policy_plan.owner == "accounts-platform"


def test_empty_routes_still_expose_an_explicit_empty_policy_plan() -> None:
    @Controller("/health")
    class HealthController:
        @Get("/")
        def read_health(self) -> dict[str, str]:
            return {"status": "ok"}

    @Module(controllers=[HealthController])
    class AppModule:
        pass

    graph = build_module_graph(AppModule)
    container = build_container(graph)

    [contract] = compile_route_contracts(graph, container)

    assert contract.policy_plan.auth is None
    assert contract.policy_plan.public is False
    assert contract.policy_plan.roles == ()
    assert contract.policy_plan.permissions == ()
    assert contract.policy_plan.rate_limit is None
    assert contract.policy_plan.cache is None
    assert contract.policy_plan.idempotency is None
    assert contract.policy_plan.audit is None
    assert contract.policy_plan.owner is None
    assert contract.policy_plan.deprecation is None