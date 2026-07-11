"""Unit tests for compiled route policy plans."""

from __future__ import annotations

import pytest

from bustan import Controller, Get, Module, SkipThrottle
from bustan.core.errors import RouteDefinitionError
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


def test_public_controller_does_not_disable_handler_access_requirements() -> None:
    @Public()
    @Controller("/mixed")
    class MixedController:
        @Get("/open")
        def read_open(self) -> dict[str, str]:
            return {"status": "ok"}

        @Auth("jwt")
        @Roles("admin")
        @Get("/locked")
        def read_locked(self) -> dict[str, str]:
            return {"status": "ok"}

    @Module(controllers=[MixedController])
    class AppModule:
        pass

    graph = build_module_graph(AppModule)
    container = build_container(graph)

    contracts = compile_route_contracts(graph, container)
    plans_by_handler = {contract.handler_name: contract.policy_plan for contract in contracts}

    assert plans_by_handler["read_open"].public is True
    assert plans_by_handler["read_locked"].public is False
    assert plans_by_handler["read_locked"].auth is not None
    assert plans_by_handler["read_locked"].roles == ("admin",)


def test_handler_public_still_overrides_controller_access_requirements() -> None:
    @Auth("jwt")
    @Controller("/accounts")
    class AccountsController:
        @Public()
        @Get("/login")
        def login(self) -> dict[str, str]:
            return {"status": "ok"}

    @Module(controllers=[AccountsController])
    class AppModule:
        pass

    graph = build_module_graph(AppModule)
    container = build_container(graph)

    [contract] = compile_route_contracts(graph, container)

    assert contract.policy_plan.public is True


def test_contradictory_public_and_requirements_at_one_level_are_rejected() -> None:
    @Controller("/handler-conflict")
    class HandlerConflictController:
        @Public()
        @Auth("jwt")
        @Get("/")
        def read(self) -> dict[str, str]:
            return {"status": "ok"}

    @Module(controllers=[HandlerConflictController])
    class HandlerConflictModule:
        pass

    graph = build_module_graph(HandlerConflictModule)
    container = build_container(graph)

    with pytest.raises(RouteDefinitionError, match="handler level"):
        compile_route_contracts(graph, container)

    @Public()
    @Roles("admin")
    @Controller("/controller-conflict")
    class ControllerConflictController:
        @Get("/")
        def read(self) -> dict[str, str]:
            return {"status": "ok"}

    @Module(controllers=[ControllerConflictController])
    class ControllerConflictModule:
        pass

    graph = build_module_graph(ControllerConflictModule)
    container = build_container(graph)

    with pytest.raises(RouteDefinitionError, match="controller level"):
        compile_route_contracts(graph, container)


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