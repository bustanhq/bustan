"""Unit tests for ApplicationContext and create_app_context()."""

from __future__ import annotations

import pytest
from bustan import Module, Injectable, create_app_context, ApplicationContext


@Injectable()
class ConfigService:
    def get_env(self) -> str:
        return "test"


@Module(providers=[ConfigService], exports=[ConfigService])
class AppModule:
    pass


def test_create_app_context_basic() -> None:
    context = create_app_context(AppModule)
    assert isinstance(context, ApplicationContext)
    
    # Context should not have HTTP properties
    assert not hasattr(context, "listen")
    assert not hasattr(context, "starlette_app")


def test_application_context_di() -> None:
    context = create_app_context(AppModule)
    service = context.get(ConfigService)
    assert isinstance(service, ConfigService)
    assert service.get_env() == "test"


@pytest.mark.anyio
async def test_application_context_close() -> None:
    context = create_app_context(AppModule)
    # close() should be callable
    await context.close()
