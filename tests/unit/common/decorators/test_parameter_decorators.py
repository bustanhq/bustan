"""Unit tests for parameter binding decorators."""

from __future__ import annotations

from typing import Any, cast

import pytest

from bustan import (
    Body,
    Cookies,
    Header,
    HostParam,
    Ip,
    Param,
    Query,
    UploadedFile,
    UploadedFiles,
    create_param_decorator,
)
from bustan.common.decorators.parameter import (
    _BodyMarker,
    _CookiesMarker,
    _CustomParameterDecorator,
    _CustomParameterMarker,
    _HeaderMarker,
    _HostParamMarker,
    _IpMarker,
    _MarkerCallable,
    _ParamMarker,
    _QueryMarker,
    _UploadedFileMarker,
    _UploadedFilesMarker,
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


def test_extended_parameter_markers_can_be_used_bare_or_called() -> None:
    assert isinstance(Cookies, _MarkerCallable)
    assert isinstance(Ip, _MarkerCallable)
    assert isinstance(HostParam, _MarkerCallable)
    assert isinstance(UploadedFile, _MarkerCallable)
    assert isinstance(UploadedFiles, _MarkerCallable)

    assert isinstance(Cookies("session"), _CookiesMarker)
    assert isinstance(Ip, _MarkerCallable)
    assert isinstance(HostParam("host"), _HostParamMarker)
    assert isinstance(UploadedFile("avatar"), _UploadedFileMarker)
    assert isinstance(UploadedFiles("attachments"), _UploadedFilesMarker)


def test_ip_marker_does_not_support_alias() -> None:
    assert repr(Ip) == "Ip"
    assert not hasattr(_IpMarker(), "alias")
    with pytest.raises(TypeError):
        Ip("something")


def test_host_param_marker_repr_includes_alias_when_provided() -> None:
    assert repr(HostParam) == "HostParam"
    assert repr(HostParam("x-forwarded-host")) == "HostParam('x-forwarded-host')"
    called = HostParam("x-forwarded-host")
    assert isinstance(called, _HostParamMarker)
    assert called.alias == "x-forwarded-host"


def test_marker_callable_equality_and_hashing() -> None:
    assert Body == Body
    assert Body != Query
    assert hash(Body) == hash(Body)
    assert hash(Body) != hash(Query)
    # Check that called markers with same alias are equal
    assert Body("a") == Body("a")
    assert Body("a") != Body("b")


def test_custom_parameter_decorator_can_be_used_bare_or_called() -> None:
    CurrentUser = create_param_decorator(lambda data, ctx: data, name="CurrentUser")

    assert isinstance(CurrentUser, _CustomParameterDecorator)
    assert CurrentUser.data is None
    assert repr(CurrentUser) == "CurrentUser"

    called = CurrentUser("email")
    assert isinstance(called, _CustomParameterMarker)
    assert called.data == "email"
    assert repr(called) == "CurrentUser('email')"


def test_custom_parameter_decorator_requires_a_callable_factory() -> None:
    with pytest.raises(TypeError, match="callable"):
        create_param_decorator(cast(Any, object()))
