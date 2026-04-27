"""Unit tests for route versioning support."""

from __future__ import annotations

from bustan import Controller, Get, Module, VERSION_NEUTRAL, VersioningOptions, VersioningType
from bustan.core.ioc.container import build_container
from bustan.core.module.graph import build_module_graph
from bustan.platform.http.routing import compile_routes


def test_compile_routes_applies_uri_versioning() -> None:
    @Controller("/users", version="1")
    class UsersController:
        @Get("/")
        def index(self) -> dict[str, str]:
            return {"status": "ok"}

    @Module(controllers=[UsersController])
    class AppModule:
        pass

    graph = build_module_graph(AppModule)
    routes = compile_routes(
        graph,
        build_container(graph),
        versioning=VersioningOptions(type=VersioningType.URI),
    )

    assert {route.path for route in routes} == {"/v1/users"}


def test_compile_routes_keeps_version_neutral_paths_unprefixed() -> None:
    @Controller("/users", version=VERSION_NEUTRAL)
    class UsersController:
        @Get("/")
        def index(self) -> dict[str, str]:
            return {"status": "ok"}

    @Module(controllers=[UsersController])
    class AppModule:
        pass

    graph = build_module_graph(AppModule)
    routes = compile_routes(
        graph,
        build_container(graph),
        versioning=VersioningOptions(type=VersioningType.URI),
    )

    assert {route.path for route in routes} == {"/users"}
