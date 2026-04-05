"""Helpers for assembling test modules and applications."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import cast

from starlette.applications import Starlette

from ..application import create_app
from ..container import ContainerAdapter
from ..decorators import Module


def create_test_module(
    *,
    name: str = "TestModule",
    imports: Iterable[type[object]] | None = None,
    controllers: Iterable[type[object]] | None = None,
    providers: Iterable[type[object] | dict[str, object]] | None = None,
    exports: Iterable[object] | None = None,
) -> type[object]:
    """Create a throwaway decorated module for isolated tests."""

    test_module_cls = cast(type[object], type(name, (), {}))
    return Module(
        imports=imports,
        controllers=controllers,
        providers=providers,
        exports=exports,
    )(test_module_cls)


def create_test_app(
    root_module: type[object],
    *,
    provider_overrides: Mapping[object, object] | None = None,
) -> Starlette:
    """Create an application and apply any requested provider overrides."""

    application = create_app(root_module)
    container = cast(ContainerAdapter, application.state.bustan_container)

    if provider_overrides is not None:
        for token, replacement in provider_overrides.items():
            container.set_provider_override(token, replacement)

    return application