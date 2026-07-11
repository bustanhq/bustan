"""Unit tests for route diagnostics and snapshots."""

from __future__ import annotations

import pytest

from bustan import Controller, Get, Module
from bustan.core.errors import RouteDefinitionError
from bustan.core.ioc.container import build_container
from bustan.core.module.graph import build_module_graph
from bustan.platform.http.compiler import compile_route_contracts
from bustan.platform.http.registry import RouteRegistry


def test_route_registry_reports_both_handlers_for_duplicate_routes() -> None:
    @Controller("/users")
    class UsersController:
        @Get("/")
        def index(self) -> dict[str, str]:
            return {"controller": "users"}

    @Controller("/users")
    class ProfilesController:
        @Get("/")
        def index(self) -> dict[str, str]:
            return {"controller": "profiles"}

    @Module(controllers=[UsersController, ProfilesController])
    class AppModule:
        pass

    graph = build_module_graph(AppModule)
    contracts = compile_route_contracts(graph, build_container(graph))

    with pytest.raises(RouteDefinitionError, match="UsersController.index.*ProfilesController.index"):
        RouteRegistry(contracts).validate()


def test_route_registry_reports_wildcard_conflict_dimension() -> None:
    @Controller("/files")
    class StaticWildcardController:
        @Get("/*")
        def read_any(self) -> dict[str, str]:
            return {"kind": "star"}

    @Controller("/files")
    class NamedWildcardController:
        @Get("/{*path}")
        def read_named(self, path: str) -> dict[str, str]:
            return {"path": path}

    @Module(controllers=[StaticWildcardController, NamedWildcardController])
    class AppModule:
        pass

    graph = build_module_graph(AppModule)
    contracts = compile_route_contracts(graph, build_container(graph))

    with pytest.raises(RouteDefinitionError, match="path pattern"):
        RouteRegistry(contracts).validate()


def test_route_registry_snapshot_is_deterministically_sorted() -> None:
    @Controller("/zeta")
    class ZetaController:
        @Get("/")
        def index(self) -> dict[str, str]:
            return {"controller": "zeta"}

    @Controller("/alpha")
    class AlphaController:
        @Get("/")
        def index(self) -> dict[str, str]:
            return {"controller": "alpha"}

    @Module(controllers=[ZetaController, AlphaController])
    class AppModule:
        pass

    graph = build_module_graph(AppModule)
    contracts = compile_route_contracts(graph, build_container(graph))
    snapshot = RouteRegistry(contracts).snapshot()

    assert [item["path"] for item in snapshot] == ["/alpha", "/zeta"]
    assert snapshot[0]["controller"] == "AlphaController"
    assert snapshot[1]["controller"] == "ZetaController"


def test_route_registry_treats_distinct_hosts_as_distinct_routes() -> None:
    @Controller("/users", host="api.example.test")
    class UsersController:
        @Get("/")
        def index(self) -> dict[str, str]:
            return {"controller": "users"}

    @Controller("/users", host="admin.example.test")
    class AdminUsersController:
        @Get("/")
        def index(self) -> dict[str, str]:
            return {"controller": "admin-users"}

    @Module(controllers=[UsersController, AdminUsersController])
    class AppModule:
        pass

    graph = build_module_graph(AppModule)
    contracts = compile_route_contracts(graph, build_container(graph))

    RouteRegistry(contracts).validate()