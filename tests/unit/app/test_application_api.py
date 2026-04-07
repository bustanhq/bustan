"""Unit tests for the Application public API."""

from __future__ import annotations

import pytest
from bustan import Module, Injectable, create_app


@Injectable()
class MyService:
    def greet(self) -> str:
        return "hello"


@Module(providers=[MyService], exports=[MyService])
class AppModule:
    pass


def test_application_get_resolve() -> None:
    app = create_app(AppModule)

    # Test get()
    service = app.get(MyService)
    assert isinstance(service, MyService)
    assert service.greet() == "hello"

    # Test resolve() alias
    service_alias = app.resolve(MyService)
    assert service_alias is service


@pytest.mark.anyio
async def test_application_close() -> None:
    app = create_app(AppModule)
    # For now close() is a no-op but it should be callable
    await app.close()


def test_application_root_module() -> None:
    app = create_app(AppModule)
    # Testing internal root module state
    assert app._root_module is AppModule
