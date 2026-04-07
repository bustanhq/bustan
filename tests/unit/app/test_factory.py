"""Unit tests for the application factory."""

from __future__ import annotations

from starlette.applications import Starlette

from bustan import Module, Controller, Get, create_app, Application


@Module()
class RootModule:
    pass


def test_create_app_basic() -> None:
    app = create_app(RootModule)
    assert isinstance(app, Application)
    server = app.get_http_server()
    assert isinstance(server, Starlette)
    assert server.debug is False


def test_create_app_with_debug() -> None:
    app = create_app(RootModule, debug=True)
    assert app.get_http_server().debug is True


def test_create_app_with_controllers() -> None:
    @Controller("/test")
    class TestController:
        @Get("/")
        def index(self):
            return "ok"

    @Module(controllers=[TestController])
    class AppModule:
        pass

    app = create_app(AppModule)
    # Check routes directly instead of controllers property
    assert "/test" in app.routes
