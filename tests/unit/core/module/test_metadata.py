"""Unit tests for metadata storage and route discovery helpers."""

from bustan import Controller, Get, Injectable, Module
from bustan.common.types import ProviderScope
from bustan.core.ioc.registry import normalize_provider
from bustan.core.module.metadata import get_module_metadata
from bustan.platform.http.metadata import (
    ControllerRouteDefinition,
    get_controller_metadata,
    get_route_metadata,
    iter_controller_routes,
)


def test_module_and_provider_metadata_are_not_inherited_by_default() -> None:
    # One rule for every decorator: metadata describes the class it was written on,
    # and an undecorated subclass has none until it is asked for one. A subclass that
    # answers with its parent's provider metadata is registered under the parent's
    # token, so the subclass is never constructed and can never be resolved by name.
    @Module()
    class BaseModule:
        pass

    class DerivedModule(BaseModule):
        pass

    @Injectable
    class BaseProvider:
        pass

    class DerivedProvider(BaseProvider):
        pass

    assert get_module_metadata(BaseModule) is not None
    assert get_module_metadata(DerivedModule) is None
    assert get_module_metadata(DerivedModule, inherit=True) == get_module_metadata(BaseModule)

    assert normalize_provider(BaseProvider, BaseModule).token is BaseProvider

    # An undecorated subclass binds as itself with the default lifetime, so it is the
    # class that gets constructed and the name it was registered under resolves.
    derived_binding = normalize_provider(DerivedProvider, BaseModule)
    assert derived_binding.token is DerivedProvider
    assert derived_binding.target is DerivedProvider
    assert derived_binding.scope is ProviderScope.SINGLETON


def test_controller_metadata_is_not_inherited_by_default() -> None:
    @Controller("/base")
    class BaseController:
        pass

    class DerivedController(BaseController):
        pass

    assert get_controller_metadata(BaseController) is not None
    assert get_controller_metadata(DerivedController) is None
    assert get_controller_metadata(DerivedController, inherit=True) == get_controller_metadata(
        BaseController
    )


def test_iter_controller_routes_includes_inherited_handlers() -> None:
    class BaseController:
        @Get("/items")
        def list_items(self) -> None:
            return None

    class DerivedController(BaseController):
        pass

    route_metadata = get_route_metadata(BaseController.list_items)
    assert route_metadata is not None

    assert iter_controller_routes(DerivedController) == (
        ControllerRouteDefinition(
            handler_name="list_items",
            handler=BaseController.list_items,
            route=route_metadata,
        ),
    )


def test_iter_controller_routes_respects_method_overrides() -> None:
    class BaseController:
        @Get("/items")
        def list_items(self) -> None:
            return None

    class DerivedController(BaseController):
        def list_items(self) -> None:
            return None

    assert iter_controller_routes(DerivedController) == ()
