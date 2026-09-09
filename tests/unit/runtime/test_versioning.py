"""Unit tests for route versioning support."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from bustan import VERSION_NEUTRAL, Controller, Get, Module, VersioningOptions, VersioningType
from bustan.contracts import HttpResponse
from bustan.kernel.errors import RouteDefinitionError
from bustan.kernel.ioc.container import build_container
from bustan.kernel.module.graph import build_module_graph
from bustan.runtime.routing import compile_routes
from bustan.runtime.versioning import extract_request_version, normalize_versions

if TYPE_CHECKING:
    from tests.conftest import HttpRequestFactory, RequestFactory


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


def test_compile_routes_raises_on_duplicate_version_neutral_handlers_for_header_versioning() -> (
    None
):
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


def test_versioning_helpers_extract_versions_from_header_and_media_type_requests(
    build_request: RequestFactory,
) -> None:
    header_request = build_request(headers=[(b"x-api-version", b"2")])
    media_type_request = build_request(headers=[(b"accept", b"application/json; version=3")])
    default_request = build_request()

    assert normalize_versions(None) == ()
    assert normalize_versions("1") == ("1",)
    assert normalize_versions(["1", "2"]) == ("1", "2")
    assert (
        extract_request_version(
            header_request,
            VersioningOptions(type=VersioningType.HEADER, default_version="1"),
        )
        == "2"
    )
    assert (
        extract_request_version(
            media_type_request,
            VersioningOptions(type=VersioningType.MEDIA_TYPE, default_version="1"),
        )
        == "3"
    )
    assert (
        extract_request_version(
            default_request,
            VersioningOptions(type=VersioningType.MEDIA_TYPE, default_version="1"),
        )
        == "1"
    )
    assert (
        extract_request_version(
            default_request,
            VersioningOptions(type=VersioningType.URI, default_version="1"),
        )
        == "1"
    )


@pytest.mark.anyio
async def test_a_version_nothing_serves_is_refused_the_way_an_unmatched_path_is(
    build_http_request: HttpRequestFactory,
) -> None:
    """A retired version and a path nothing is registered at are one answer to a caller.

    Both mean nothing here serves what was asked for, and a client on a version the
    deployment has moved past is the caller most likely to meet one of them, so the
    document it reads is the document the error model documents.
    """

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
        versioning=VersioningOptions(type=VersioningType.HEADER),
    )
    handler = next(route.handler for route in routes if route.path == "/users")
    assert handler is not None

    response = await handler(build_http_request(path="/users", headers=[(b"x-api-version", b"9")]))

    assert isinstance(response, HttpResponse)
    assert response.status_code == 404
    assert response.media_type == "application/problem+json"
    assert json.loads(response.body)["type"] == "https://bustan.dev/problems/not-found"
