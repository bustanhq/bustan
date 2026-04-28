"""Unit tests for application CORS support."""

from __future__ import annotations

from typing import Any, cast

from starlette.testclient import TestClient

from bustan import Controller, CorsOptions, Get, Module, create_app


def test_application_enable_cors_adds_cors_headers() -> None:
    @Controller("/")
    class AppController:
        @Get("/")
        def index(self) -> dict[str, str]:
            return {"status": "ok"}

    @Module(controllers=[AppController])
    class AppModule:
        pass

    app = create_app(AppModule)
    app.enable_cors(CorsOptions(origins=["https://example.com"]))

    with TestClient(cast(Any, app)) as client:
        response = client.get("/", headers={"origin": "https://example.com"})

    assert response.headers["access-control-allow-origin"] == "https://example.com"
