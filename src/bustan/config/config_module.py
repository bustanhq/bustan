"""Dynamic config module helpers."""

from __future__ import annotations

from typing import Any, cast

from ..core.ioc.tokens import InjectionToken
from ..core.module.decorators import Module
from ..core.module.dynamic import DynamicModule
from .config_service import ConfigService
from .env_loader import load_env

CONFIG_VALUES = InjectionToken[dict[str, Any]]("CONFIG_VALUES")


@Module()
class _ConfigModuleBase:
    pass


class ConfigModule:
    """Factory helpers for configuration-backed dynamic modules."""

    @staticmethod
    def for_root(
        *,
        env_file: str | list[str] | None = None,
        validation_schema: type | None = None,
        ignore_env_file: bool = False,
        is_global: bool = True,
    ) -> DynamicModule:
        values = load_env(env_file, ignore_env_file=ignore_env_file)
        if validation_schema is not None:
            values = _validate_values(validation_schema, values)

        return DynamicModule(
            module=_ConfigModuleBase,
            providers=(
                {"provide": CONFIG_VALUES, "use_value": values},
                {
                    "provide": ConfigService,
                    "use_factory": _build_config_service,
                    "inject": (CONFIG_VALUES,),
                },
            ),
            exports=(ConfigService, CONFIG_VALUES),
            is_global=is_global,
        )


def _build_config_service(values: dict[str, Any]) -> ConfigService:
    return ConfigService(values)


def _validate_values(schema: type, values: dict[str, Any]) -> dict[str, Any]:
    if hasattr(schema, "model_validate"):
        model_schema = cast(Any, schema)
        model = model_schema.model_validate(values)
        return cast(dict[str, Any], model.model_dump())
    instance = schema(**values)
    return {
        key: getattr(instance, key)
        for key in dir(instance)
        if not key.startswith("_") and not callable(getattr(instance, key))
    }
