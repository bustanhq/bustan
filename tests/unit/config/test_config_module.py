"""Unit tests for the config module."""

from __future__ import annotations

from pydantic import BaseModel

from bustan import ConfigModule, ConfigService, Module, create_app


class Settings(BaseModel):
    port: int


def test_config_module_loads_env_files(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("APP_NAME=bustan\n", encoding="utf-8")

    @Module(imports=[ConfigModule.for_root(env_file=str(env_file))])
    class AppModule:
        pass

    app = create_app(AppModule)

    assert app.get(ConfigService).get("APP_NAME") == "bustan"


def test_config_module_validates_with_pydantic_models(monkeypatch) -> None:
    monkeypatch.setenv("port", "4000")

    @Module(imports=[ConfigModule.for_root(validation_schema=Settings)])
    class AppModule:
        pass

    app = create_app(AppModule)

    assert app.get(ConfigService).get("port") == 4000


def test_config_module_is_global_by_default() -> None:
    @Module()
    class FeatureModule:
        pass

    @Module(imports=[ConfigModule.for_root(), FeatureModule])
    class AppModule:
        pass

    app = create_app(AppModule)

    assert isinstance(app._container.resolve(ConfigService, module=FeatureModule), ConfigService)
