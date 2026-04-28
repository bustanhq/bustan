"""Unit tests for route versioning support."""

from __future__ import annotations

import pytest

from bustan import Controller, Get, Module, VERSION_NEUTRAL, VersioningOptions, VersioningType
from bustan.core.errors import RouteDefinitionError
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


def _compile_header(module_cls) -> tuple:
    graph = build_module_graph(module_cls)
    return compile_routes(
        graph,
        build_container(graph),
        versioning=VersioningOptions(type=VersioningType.HEADER),
    )


def test_compile_routes_raises_on_duplicate_unversioned_handlers_for_header_versioning() -> None:
    @Controller("/items")
    class ItemsControllerA:
        @Get("/")
        def index(self) -> dict[str, str]:
            return {"controller": "a"}

    @Controller("/items")
    class ItemsControllerB:
        @Get("/")
        def index(self) -> dict[str, str]:
            return {"controller": "b"}

    @Module(controllers=[ItemsControllerA, ItemsControllerB])
    class AppModule:
        pass

    with pytest.raises(RouteDefinitionError, match="version-neutral"):
        _compile_header(AppModule)


def test_compile_routes_raises_on_duplicate_version_neutral_handlers_for_header_versioning() -> None:
    @Controller("/items", version=VERSION_NEUTRAL)
    class ItemsControllerA:
        @Get("/")
        def index(self) -> dict[str, str]:
            return {"controller": "a"}

    @Controller("/items", version=VERSION_NEUTRAL)
    class ItemsControllerB:
        @Get("/")
        def index(self) -> dict[str, str]:
            return {"controller": "b"}

    @Module(controllers=[ItemsControllerA, ItemsControllerB])
    class AppModule:
        pass

    with pytest.raises(RouteDefinitionError, match="version-neutral"):
        _compile_header(AppModule)


def test_compile_routes_raises_on_overlapping_concrete_versions_for_header_versioning() -> None:
    @Controller("/items", version=["1", "2"])
    class ItemsControllerA:
        @Get("/")
        def index(self) -> dict[str, str]:
            return {"controller": "a"}

    @Controller("/items", version=["2", "3"])
    class ItemsControllerB:
        @Get("/")
        def index(self) -> dict[str, str]:
            return {"controller": "b"}

    @Module(controllers=[ItemsControllerA, ItemsControllerB])
    class AppModule:
        pass

    with pytest.raises(RouteDefinitionError, match="Overlapping versions"):
        _compile_header(AppModule)


def test_compile_routes_allows_disjoint_concrete_versions_for_header_versioning() -> None:
    @Controller("/items", version="1")
    class ItemsControllerV1:
        @Get("/")
        def index(self) -> dict[str, str]:
            return {"version": "1"}

    @Controller("/items", version="2")
    class ItemsControllerV2:
        @Get("/")
        def index(self) -> dict[str, str]:
            return {"version": "2"}

    @Module(controllers=[ItemsControllerV1, ItemsControllerV2])
    class AppModule:
        pass

    routes = _compile_header(AppModule)
    assert len(routes) == 1
