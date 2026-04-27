"""Unit tests for the built-in pipe collection."""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, cast

import pytest
from pydantic import BaseModel

from bustan import (
    DefaultValuePipe,
    ParseArrayPipe,
    ParseBoolPipe,
    ParseEnumPipe,
    ParseFloatPipe,
    ParseIntPipe,
    ParseUUIDPipe,
    ValidationPipe,
)
from bustan.core.errors import BadRequestException
from bustan.common.types import RouteMetadata
from bustan.core.module.dynamic import ModuleInstanceKey
from bustan.pipeline.context import ParameterContext, RequestContext
from bustan.platform.http.metadata import ControllerRouteDefinition
from starlette.requests import Request

if TYPE_CHECKING:
    from bustan.core.ioc.container import Container


class Color(Enum):
    RED = "red"
    BLUE = "blue"


class PayloadModel(BaseModel):
    name: str
    admin: bool


@pytest.mark.anyio
async def test_parse_pipes_coerce_expected_types() -> None:
    context = _parameter_context()

    assert await ParseIntPipe().transform("42", context) == 42
    assert await ParseFloatPipe().transform("3.14", context) == 3.14
    assert await ParseBoolPipe().transform("true", context) is True
    assert await ParseArrayPipe().transform("a,b,c", context) == ["a", "b", "c"]
    assert await ParseEnumPipe(Color).transform("red", context) is Color.RED
    assert await DefaultValuePipe("fallback").transform(None, context) == "fallback"
    assert str(await ParseUUIDPipe().transform("12345678-1234-5678-1234-567812345678", context)) == (
        "12345678-1234-5678-1234-567812345678"
    )


@pytest.mark.anyio
async def test_parse_pipes_raise_bad_request_for_invalid_values() -> None:
    context = _parameter_context()

    with pytest.raises(BadRequestException):
        await ParseIntPipe().transform("not-an-int", context)

    with pytest.raises(BadRequestException):
        await ParseBoolPipe().transform("maybe", context)

    with pytest.raises(BadRequestException):
        await ParseEnumPipe(Color).transform("green", context)


@pytest.mark.anyio
async def test_validation_pipe_validates_pydantic_models() -> None:
    context = _parameter_context(annotation=PayloadModel)

    value = await ValidationPipe().transform({"name": "Ada", "admin": True}, context)

    assert isinstance(value, PayloadModel)
    assert value.name == "Ada"


@pytest.mark.anyio
async def test_validation_pipe_raises_bad_request_on_invalid_models() -> None:
    context = _parameter_context(annotation=PayloadModel)

    with pytest.raises(BadRequestException):
        await ValidationPipe().transform({"name": "Ada"}, context)


def _parameter_context(annotation: object = str) -> ParameterContext:
    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    request = Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/",
            "raw_path": b"/",
            "query_string": b"",
            "headers": [(b"host", b"testserver")],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
            "path_params": {},
        },
        receive,
    )
    request_context = RequestContext(
        request=request,
        module=ModuleInstanceKey(module=object, instance_id="test"),
        controller_type=object,
        controller=object(),
        route=ControllerRouteDefinition(
            handler_name="test",
            handler=_handler,
            route=RouteMetadata(method="GET", path="/", name="test"),
        ),
        container=cast("Container", object()),
    )
    return ParameterContext(
        request_context=request_context,
        name="value",
        source="query",
        annotation=annotation,
        value=None,
    )


def _handler() -> None:
    return None
