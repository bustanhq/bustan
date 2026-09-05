"""A whole application, served by the adapter that binds no web framework.

Every request here goes through ``create_test_client``, because that client is what a
conformance suite asks an adapter for and driving these tests any other way would leave
it untested.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from bustan import Controller, Get, Injectable, Module, Post, Scope, create_app
from bustan.adapters.asgi import AsgiAdapter, AsgiTestClient
from bustan.contracts import HttpRequest
from bustan.openapi import SwaggerOptions
from bustan.openapi.document_builder import DocumentBuilder

if TYPE_CHECKING:
    from bustan.app.application import Application


@dataclass(frozen=True, slots=True)
class CreateUserPayload:
    name: str
    admin: bool


def _build(
    root_module: type[object], *, swagger: SwaggerOptions | None = None
) -> tuple[Application, AsgiTestClient]:
    """Build an application on the ASGI adapter, with its lifecycle on the lifespan.

    The framework hands its own lifespan to the adapter it builds itself; an adapter
    passed in brings its own, so this is where an application choosing this adapter
    connects startup and shutdown to the transport that will announce them.
    """

    built: dict[str, Application] = {}

    @asynccontextmanager
    async def lifespan(_app: object) -> AsyncIterator[None]:
        await built["application"].init()
        try:
            yield
        finally:
            await built["application"].close()

    adapter = AsgiAdapter(lifespan=lifespan)
    application = create_app(root_module, adapter=adapter, swagger=swagger)
    built["application"] = application
    return application, adapter.create_test_client()


@pytest.fixture
def greeting_file(tmp_path: Path) -> Path:
    path = tmp_path / "greeting.txt"
    path.write_text("hello file", encoding="utf-8")
    return path


def test_an_application_on_this_adapter_serves_every_shape_of_route(
    greeting_file: Path,
) -> None:
    events: list[str] = []

    @Injectable
    class UsersService:
        def describe(self, user_id: int) -> str:
            return f"user-{user_id}"

    @Controller("/users")
    class UsersController:
        def __init__(self, users_service: UsersService) -> None:
            self.users_service = users_service

        @Get("/{user_id}")
        def read_user(
            self, request: HttpRequest, user_id: int, verbose: bool = False, page: int = 1
        ) -> dict[str, object]:
            return {
                "path": request.url.path,
                "described": self.users_service.describe(user_id),
                "user_id": user_id,
                "verbose": verbose,
                "page": page,
            }

        @Post("/")
        def create_user(self, payload: CreateUserPayload) -> dict[str, object]:
            return {"name": payload.name, "admin": payload.admin}

        @Get("/{user_id}/report")
        def stream_report(self, user_id: int) -> Iterator[bytes]:
            yield b"report for "
            yield str(user_id).encode()

        @Get("/greeting/file")
        def read_file(self) -> Path:
            return greeting_file

    @Module(controllers=[UsersController], providers=[UsersService], exports=[UsersService])
    class AppModule:
        def on_application_bootstrap(self) -> None:
            events.append("startup")

        def on_application_shutdown(self, signal: str | None) -> None:
            events.append("shutdown")

    _application, client = _build(AppModule)

    with client:
        assert events == ["startup"]
        read = client.get("/users/41?verbose=true&page=2")
        created = client.post("/users", json={"name": "Ada", "admin": True})
        streamed = client.get("/users/7/report")
        served_file = client.get("/users/greeting/file")

    assert events == ["startup", "shutdown"]
    assert read.status_code == 200
    assert read.json() == {
        "path": "/users/41",
        "described": "user-41",
        "user_id": 41,
        "verbose": True,
        "page": 2,
    }
    assert created.status_code == 200
    assert created.json() == {"name": "Ada", "admin": True}
    assert streamed.status_code == 200
    assert streamed.text == "report for 7"
    assert served_file.status_code == 200
    assert served_file.text == "hello file"
    assert served_file.headers["content-length"] == "10"


def test_the_framework_reaches_the_application_through_this_adapter_too() -> None:
    @Injectable(scope="request")
    class RequestIdentity:
        def __init__(self) -> None:
            self.value = object()

    @Controller("/identity", scope=Scope.REQUEST)
    class IdentityController:
        def __init__(self, identity: RequestIdentity) -> None:
            self.identity = identity

        @Get("/")
        def read(self) -> dict[str, str]:
            return {"identity": str(id(self.identity.value))}

    @Module(controllers=[IdentityController], providers=[RequestIdentity])
    class AppModule:
        pass

    application, client = _build(AppModule)

    with client:
        first = client.get("/identity").json()["identity"]
        second = client.get("/identity").json()["identity"]

    assert first != second
    assert application.get_http_server().state.bustan_application is application


def test_a_binding_failure_is_answered_by_the_frameworks_error_model() -> None:
    @Controller("/users")
    class UsersController:
        @Get("/{user_id}")
        def read_user(self, user_id: int) -> dict[str, int]:
            return {"user_id": user_id}

    @Module(controllers=[UsersController])
    class AppModule:
        pass

    _application, client = _build(AppModule)

    with client:
        response = client.get("/users/not-a-number")

    assert response.status_code == 400
    assert response.json()["detail"].startswith("Could not bind path parameter 'user_id'")


def test_the_openapi_document_and_its_viewer_serve_through_this_adapter() -> None:
    @Controller("/health")
    class HealthController:
        @Get("/")
        def read(self) -> dict[str, str]:
            return {"status": "ok"}

    @Module(controllers=[HealthController])
    class AppModule:
        pass

    # The OpenAPI routes are the framework's own, registered through the adapter port
    # rather than compiled from a controller, so serving them proves the port carries a
    # route the framework built as well as one a controller declared.
    swagger = SwaggerOptions(path="/openapi.json", document_builder=DocumentBuilder())
    _application, client = _build(AppModule, swagger=swagger)

    with client:
        document = client.get("/openapi.json")
        viewer = client.get("/openapi.json/docs")
        health = client.get("/health")

    assert document.status_code == 200
    assert document.json()["openapi"].startswith("3.")
    assert viewer.status_code == 200
    assert viewer.headers["content-type"] == "text/html; charset=utf-8"
    assert "swagger-ui" in viewer.text
    assert health.json() == {"status": "ok"}


def test_the_adapter_answers_a_request_no_route_matched() -> None:
    @Controller("/health")
    class HealthController:
        @Get("/")
        def read(self) -> dict[str, str]:
            return {"status": "ok"}

    @Module(controllers=[HealthController])
    class AppModule:
        pass

    _application, client = _build(AppModule)

    with client:
        missing = client.get("/absent")
        wrong_method = client.post("/health")

    assert (missing.status_code, missing.text) == (404, "Not Found")
    assert wrong_method.status_code == 405
    assert wrong_method.headers["allow"] == "GET, HEAD"


def test_an_application_can_be_driven_without_ever_starting_its_lifespan() -> None:
    @Controller("/health")
    class HealthController:
        @Get("/")
        def read(self) -> dict[str, str]:
            return {"status": "ok"}

    @Module(controllers=[HealthController])
    class AppModule:
        pass

    _application, client = _build(AppModule)

    assert client.get("/health").json() == {"status": "ok"}


def test_the_adapters_capabilities_are_checked_before_a_route_is_compiled() -> None:
    @Controller("/admin", host="admin.example.test")
    class AdminController:
        @Get("/")
        def read(self) -> dict[str, str]:
            return {"status": "ok"}

    @Module(controllers=[AdminController])
    class AppModule:
        pass

    from bustan.errors import RouteDefinitionError

    with pytest.raises(RouteDefinitionError, match="does not support host routing"):
        create_app(AppModule, adapter=AsgiAdapter())
