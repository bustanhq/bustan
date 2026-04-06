"""Unit tests for internal utility functions."""

from __future__ import annotations

import pytest
from typing import cast
from bustan.core.utils import (
    _display_name,
    _get_metadata,
    _join_paths,
    _normalize_path,
    _qualname,
    _unwrap_handler,
)
from bustan.core.errors import RouteDefinitionError


class MockModule:
    __module__ = "test_module"
    __qualname__ = "TestClass"
    __name__ = "TestClass"


class MockInstanceKey:
    def __init__(self, module, instance_id):
        self.module = module
        self.instance_id = instance_id


def test_qualname_and_display_name() -> None:
    # Since MockModule has __module__ = "test_module", _qualname uses it
    # Note: _display_name on a class uses target.__name__. 
    # For a class MockModule, MockModule.__name__ is usually MockModule
    # unless it was assigned otherwise. But let's check the real behavior.
    assert _qualname(MockModule) == "test_module.TestClass"
    # In my manual class definition, MockModule.__name__ remains "MockModule"
    assert _display_name(MockModule) == "MockModule"
    
    key = MockInstanceKey(MockModule, "123")
    assert _qualname(key) == "test_module.TestClass[123]"
    assert _display_name(key) == "MockModule[123]"
    
    assert _qualname(123) == "123"
    assert _display_name(123) == "123"


def test_join_paths() -> None:
    assert _join_paths("", "/users") == "/users"
    assert _join_paths("/api", "/") == "/api"
    assert _join_paths("/api", "/users") == "/api/users"


def test_unwrap_handler() -> None:
    def regular_func(*args, **kwargs): pass
    assert _unwrap_handler(regular_func) is regular_func
    
    assert _unwrap_handler(staticmethod(regular_func)) is regular_func
    assert _unwrap_handler(classmethod(regular_func)) is regular_func
    assert _unwrap_handler("not a func") is None


def test_get_metadata() -> None:
    class Base:
        attr = "value"
    
    class Derived(Base):
        pass
        
    assert _get_metadata(Derived, "attr", inherit=True) == "value"
    assert _get_metadata(Derived, "attr", inherit=False) is None


def test_normalize_path_edge_cases() -> None:
    # allow_empty=True
    assert _normalize_path("", allow_empty=True, kind="prefix") == ""
    assert _normalize_path("/", allow_empty=True, kind="prefix") == ""
    
    # allow_empty=False
    with pytest.raises(RouteDefinitionError, match="Prefix cannot be empty"):
        _normalize_path("", allow_empty=False, kind="prefix")
        
    assert _normalize_path("users/", allow_empty=False, kind="path") == "/users"
    assert _normalize_path(" /api/ ", allow_empty=False, kind="prefix") == "/api"


def test_normalize_path_type_error() -> None:
    with pytest.raises(RouteDefinitionError, match="Path must be a string"):
        _normalize_path(cast(str, 123), allow_empty=True, kind="path")
