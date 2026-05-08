"""Unit tests for route versioning support."""

from __future__ import annotations

import pytest
from starlette.requests import Request

from bustan import Controller, Get, Module, VERSION_NEUTRAL, VersioningOptions, VersioningType
from bustan.core.errors import RouteDefinitionError
from bustan.core.ioc.container import build_container
from bustan.core.module.graph import build_module_graph
from bustan.platform.http.routing import compile_routes
from bustan.platform.http.versioning import extract_request_version, normalize_versions


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


def test_versioning_helpers_extract_versions_from_header_and_media_type_requests() -> None:
    header_request = _build_request(headers=[(b"x-api-version", b"2")])
    media_type_request = _build_request(headers=[(b"accept", b"application/json; version=3")])
    default_request = _build_request()

    assert normalize_versions(None) == ()
    assert normalize_versions("1") == ("1",)
    assert normalize_versions(["1", "2"]) == ("1", "2")
    assert extract_request_version(
        header_request,
        VersioningOptions(type=VersioningType.HEADER, default_version="1"),
    ) == "2"
    assert extract_request_version(
        media_type_request,
        VersioningOptions(type=VersioningType.MEDIA_TYPE, default_version="1"),
    ) == "3"
    assert extract_request_version(
        default_request,
        VersioningOptions(type=VersioningType.MEDIA_TYPE, default_version="1"),
    ) == "1"
    assert extract_request_version(
        default_request,
        VersioningOptions(type=VersioningType.URI, default_version="1"),
    ) == "1"


def _build_request(headers: list[tuple[bytes, bytes]] | None = None) -> Request:
    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/",
            "raw_path": b"/",
            "query_string": b"",
            "headers": headers or [(b"host", b"testserver")],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
            "path_params": {},
        },
        receive,
    )
