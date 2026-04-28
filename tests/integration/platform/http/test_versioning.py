"""Integration tests for header-based version dispatch."""

from __future__ import annotations

from typing import Any, cast

from starlette.testclient import TestClient

from bustan import Controller, Get, Module, VersioningOptions, VersioningType, create_app


def test_header_versioning_dispatches_to_matching_routes() -> None:
    @Controller("/users", version="1")
    class UsersV1Controller:
        @Get("/")
        def index(self) -> dict[str, str]:
            return {"version": "v1"}

    @Controller("/users", version="2")
    class UsersV2Controller:
        @Get("/")
        def index(self) -> dict[str, str]:
            return {"version": "v2"}

    @Module(controllers=[UsersV1Controller, UsersV2Controller])
    class AppModule:
        pass

    application = create_app(
        AppModule,
        versioning=VersioningOptions(type=VersioningType.HEADER, header="x-api-version"),
    )

    with TestClient(cast(Any, application)) as client:
        assert client.get("/users", headers={"x-api-version": "1"}).json() == {"version": "v1"}
        assert client.get("/users", headers={"x-api-version": "2"}).json() == {"version": "v2"}
        assert client.get("/users", headers={"x-api-version": "3"}).status_code == 404
