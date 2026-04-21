"""Unit tests for parameter binding decorators."""

from __future__ import annotations

from bustan import Body, Header, Param, Query
from bustan.common.decorators.parameter import (
    _BodyMarker,
    _HeaderMarker,
    _MarkerCallable,
    _ParamMarker,
    _QueryMarker,
)


def test_body_decorator_can_be_used_bare_or_called() -> None:
    assert isinstance(Body, _MarkerCallable)

    # Bare usage
    bare = Body
    assert bare.alias is None
    assert repr(bare) == "Body"

    # Called usage with alias
    called = Body("alias")
    assert isinstance(called, _BodyMarker)
    assert called.alias == "alias"
    assert repr(called) == "Body('alias')"


def test_query_decorator_can_be_used_bare_or_called() -> None:
    assert isinstance(Query, _MarkerCallable)

    # Bare usage
    bare = Query
    assert bare.alias is None
    assert repr(bare) == "Query"

    # Called usage with alias
    called = Query("alias")
    assert isinstance(called, _QueryMarker)
    assert called.alias == "alias"
    assert repr(called) == "Query('alias')"


def test_param_decorator_can_be_used_bare_or_called() -> None:
    assert isinstance(Param, _MarkerCallable)

    # Bare usage
    bare = Param
    assert bare.alias is None
    assert repr(bare) == "Param"

    # Called usage with alias
    called = Param("alias")
    assert isinstance(called, _ParamMarker)
    assert called.alias == "alias"
    assert repr(called) == "Param('alias')"


def test_header_decorator_can_be_used_bare_or_called() -> None:
    assert isinstance(Header, _MarkerCallable)

    # Bare usage
    bare = Header
    assert bare.alias is None
    assert repr(bare) == "Header"

    # Called usage with alias
    called = Header("X-Custom-Header")
    assert isinstance(called, _HeaderMarker)
    assert called.alias == "X-Custom-Header"
    assert repr(called) == "Header('X-Custom-Header')"


def test_marker_callable_equality_and_hashing() -> None:
    assert Body == Body
    assert Body != Query
    assert hash(Body) == hash(Body)
    assert hash(Body) != hash(Query)
    # Check that called markers with same alias are equal
    assert Body("a") == Body("a")
    assert Body("a") != Body("b")
