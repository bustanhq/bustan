"""Helpers for generating configurable dynamic modules."""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from ...common.types import (
    ClassProvider,
    ExistingProvider,
    FactoryProvider,
    Provider,
    ValueProvider,
)
from ..ioc.tokens import InjectionToken
from .decorators import Module
from .dynamic import DynamicModule


class ConfigurableModuleDefinition[OptionsT]:
    """Typed interface for generated configurable module classes."""

    @staticmethod
    def for_root(options: OptionsT, *, is_global: bool = False) -> DynamicModule:
        raise NotImplementedError

    @staticmethod
    def register(options: OptionsT, *, is_global: bool = False) -> DynamicModule:
        raise NotImplementedError

    @staticmethod
    def for_root_async(
        *,
        use_factory: Callable[..., object] | None = None,
        use_class: type[object] | None = None,
        use_existing: object | None = None,
        inject: tuple[object, ...] = (),
        imports: tuple[type[object] | DynamicModule, ...] = (),
        is_global: bool = False,
    ) -> DynamicModule:
        raise NotImplementedError

    @staticmethod
    def register_async(
        *,
        use_factory: Callable[..., object] | None = None,
        use_class: type[object] | None = None,
        use_existing: object | None = None,
        inject: tuple[object, ...] = (),
        imports: tuple[type[object] | DynamicModule, ...] = (),
        is_global: bool = False,
    ) -> DynamicModule:
        raise NotImplementedError


class ConfigurableModuleBuilder[OptionsT]:
    """Build runtime-generated module classes with for_root-style helpers."""

    def __init__(self) -> None:
        self._class_name = "ConfigurableModule"
        self._extras_providers: tuple[Provider, ...] = ()
        self._token: InjectionToken[OptionsT] | None = None

    def set_class_name(self, name: str) -> ConfigurableModuleBuilder[OptionsT]:
        self._class_name = name
        return self

    def set_extras(
        self,
        *,
        providers: tuple[Provider, ...] = (),
    ) -> ConfigurableModuleBuilder[OptionsT]:
        self._extras_providers = providers
        return self

    def build(
        self,
    ) -> tuple[type[ConfigurableModuleDefinition[OptionsT]], InjectionToken[OptionsT]]:
        """Return a generated module class and its stable options token."""
        if self._token is None:
            self._token = InjectionToken(f"{self._class_name}_OPTIONS")

        token = self._token
        extras = self._extras_providers

        @Module()
        class GeneratedModule:
            @staticmethod
            def for_root(
                options: object,
                *,
                is_global: bool = False,
            ) -> DynamicModule:
                return DynamicModule(
                    module=GeneratedModule,
                    providers=(
                        ValueProvider(provide=token, use_value=options),
                        *extras,
                    ),
                    exports=(token,),
                    is_global=is_global,
                )

            @staticmethod
            def register(
                options: object,
                *,
                is_global: bool = False,
            ) -> DynamicModule:
                return GeneratedModule.for_root(options, is_global=is_global)

            @staticmethod
            def for_root_async(
                *,
                use_factory: Callable[..., object] | None = None,
                use_class: type[object] | None = None,
                use_existing: object | None = None,
                inject: tuple[object, ...] = (),
                imports: tuple[type[object] | DynamicModule, ...] = (),
                is_global: bool = False,
            ) -> DynamicModule:
                provider: Provider
                if use_factory is not None:
                    provider = FactoryProvider(
                        provide=token, use_factory=use_factory, inject=inject
                    )
                elif use_class is not None:
                    provider = ClassProvider(provide=token, use_class=use_class)
                elif use_existing is not None:
                    provider = ExistingProvider(provide=token, use_existing=use_existing)
                else:
                    raise ValueError(
                        "for_root_async requires use_factory, use_class, or use_existing"
                    )

                return DynamicModule(
                    module=GeneratedModule,
                    providers=(provider, *extras),
                    imports=imports,
                    exports=(token,),
                    is_global=is_global,
                )

            @staticmethod
            def register_async(
                *,
                use_factory: Callable[..., object] | None = None,
                use_class: type[object] | None = None,
                use_existing: object | None = None,
                inject: tuple[object, ...] = (),
                imports: tuple[type[object] | DynamicModule, ...] = (),
                is_global: bool = False,
            ) -> DynamicModule:
                return GeneratedModule.for_root_async(
                    use_factory=use_factory,
                    use_class=use_class,
                    use_existing=use_existing,
                    inject=inject,
                    imports=imports,
                    is_global=is_global,
                )

        GeneratedModule.__name__ = self._class_name
        GeneratedModule.__qualname__ = self._class_name

        return cast(type[ConfigurableModuleDefinition[OptionsT]], GeneratedModule), token
