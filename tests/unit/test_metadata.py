"""Unit tests for metadata storage and route discovery helpers."""

from bustan import Controller, Get, Module
from bustan.metadata import (
    ControllerRouteDefinition,
    get_controller_metadata,
    get_module_metadata,
    get_route_metadata,
    iter_controller_routes,
)


def test_module_metadata_is_not_inherited_by_default() -> None:
    @Module()
    class BaseModule:
        pass

    class DerivedModule(BaseModule):
        pass

    assert get_module_metadata(BaseModule) is not None
    assert get_module_metadata(DerivedModule) is None
    assert get_module_metadata(DerivedModule, inherit=True) == get_module_metadata(BaseModule)


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