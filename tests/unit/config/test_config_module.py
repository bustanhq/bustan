"""Unit tests for the config module."""

from __future__ import annotations

from pydantic import BaseModel

from bustan import ConfigModule, ConfigService, Module, create_app
from bustan.config.config_module import _build_config_service, _validate_values
from bustan.config.env_loader import _load_env_file, load_env


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


def test_config_helpers_cover_plain_schema_and_env_loader_branches(tmp_path, monkeypatch) -> None:
    class PlainSettings:
        def __init__(self, APP_NAME: str, DEBUG: str) -> None:
            self.APP_NAME = APP_NAME
            self.DEBUG = DEBUG
            self._private = "hidden"

        def helper(self) -> str:
            return "ignored"

    env_file = tmp_path / ".env"
    env_file.write_text("# comment\nAPP_NAME=bustan\nINVALID\nDEBUG = 1\n", encoding="utf-8")
    monkeypatch.setenv("APP_NAME", "process")

    assert _load_env_file(tmp_path / "missing.env") == {}
    assert _load_env_file(env_file) == {"APP_NAME": "bustan", "DEBUG": "1"}
    assert load_env(str(env_file), ignore_env_file=True)["APP_NAME"] == "process"
    assert _validate_values(PlainSettings, {"APP_NAME": "bustan", "DEBUG": "1"}) == {
        "APP_NAME": "bustan",
        "DEBUG": "1",
    }
    assert _build_config_service({"APP_NAME": "bustan"}).get("APP_NAME") == "bustan"
