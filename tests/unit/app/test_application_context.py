"""Unit tests for ApplicationContext and create_app_context()."""

from __future__ import annotations

import pytest
from bustan import Module, Injectable, create_app_context, ApplicationContext
from bustan.core.errors import ProviderResolutionError


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


@pytest.mark.anyio
async def test_application_context_init_matches_http_startup_semantics() -> None:
    events: list[str] = []

    async def build_value() -> str:
        events.append("factory")
        return "ready"

    @Module(
        providers=[{"provide": "token", "use_factory": build_value}],
        exports=["token"],
    )
    class FeatureModule:
        pass

    @Module(imports=[FeatureModule])
    class RootModule:
        def on_module_init(self) -> None:
            events.append("init")

        def on_application_bootstrap(self) -> None:
            events.append("bootstrap")

        def on_application_shutdown(self, signal: str | None) -> None:
            events.append("shutdown")

        def on_module_destroy(self) -> None:
            events.append("destroy")

    context = create_app_context(RootModule)

    with pytest.raises(ProviderResolutionError, match="async factory"):
        context.get("token")

    await context.init()
    assert context.get("token") == "ready"
    assert events[:3] == ["factory", "init", "bootstrap"]

    await context.close()
    assert events[-2:] == ["shutdown", "destroy"]
