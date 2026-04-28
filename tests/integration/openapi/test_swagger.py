"""Integration tests for Swagger/OpenAPI endpoints."""

from __future__ import annotations

from typing import Any, cast

from starlette.testclient import TestClient

from bustan import Controller, DocumentBuilder, Get, Module, SwaggerOptions, create_app


def test_openapi_json_endpoint_returns_registered_routes() -> None:
    @Controller("/cats")
    class CatsController:
        @Get("/")
        def index(self) -> dict[str, str]:
            return {"status": "ok"}

    @Module(controllers=[CatsController])
    class AppModule:
        pass

    app = create_app(
        AppModule,
        swagger=SwaggerOptions(DocumentBuilder().set_title("Cats").set_version("1.0")),
    )

    with TestClient(cast(Any, app)) as client:
        response = client.get("/api")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert "/cats" in response.json()["paths"]


def test_swagger_ui_endpoint_returns_html() -> None:
    @Controller("/")
    class AppController:
        @Get("/")
        def index(self) -> dict[str, str]:
            return {"status": "ok"}

    @Module(controllers=[AppController])
    class AppModule:
        pass

    app = create_app(AppModule, swagger=SwaggerOptions(DocumentBuilder()))

    with TestClient(cast(Any, app)) as client:
        response = client.get("/api/docs")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "SwaggerUIBundle" in response.text
