"""Unit tests for HTTP metadata helpers."""

from __future__ import annotations

from typing import cast

import pytest

from bustan.common.types import ControllerMetadata, RouteMetadata
from bustan.core.errors import InvalidControllerError
from bustan.platform.http.metadata import (
    get_controller_metadata,
    get_route_metadata,
    iter_controller_routes,
    normalize_controller_prefix,
    normalize_route_path,
    set_controller_metadata,
    set_route_metadata,
)


def test_normalize_controller_prefix_errors() -> None:
    assert normalize_controller_prefix("users") == "/users"
    with pytest.raises(InvalidControllerError, match="Controller prefix must be a string"):
        normalize_controller_prefix(cast(str, 123))


def test_normalize_route_path_logic() -> None:
    assert normalize_route_path("info") == "/info"
    assert normalize_route_path("/") == "/"


def test_set_and_get_metadata() -> None:
    class MyController:
        pass

    metadata = ControllerMetadata(prefix="/test")
    set_controller_metadata(MyController, metadata)
    assert get_controller_metadata(MyController) == metadata


def test_set_and_get_route_metadata() -> None:
    def my_handler():
        pass

    metadata = RouteMetadata(method="GET", path="/", name="h")
    set_route_metadata(my_handler, metadata)
    assert get_route_metadata(my_handler) == metadata

    assert get_route_metadata(None) is None


def test_iter_controller_routes_mro() -> None:
    class Base:
        def base_handler(self):
            pass

        set_route_metadata(base_handler, RouteMetadata("GET", "/base", "base_handler"))

    class Derived(Base):
        def derived_handler(self):
            pass

        set_route_metadata(derived_handler, RouteMetadata("POST", "/derived", "derived_handler"))

    routes = iter_controller_routes(Derived)
    names = {r.handler_name for r in routes}
    assert "base_handler" in names
    assert "derived_handler" in names
    assert len(routes) == 2
