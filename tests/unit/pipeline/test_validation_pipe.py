"""Unit tests for ValidationPipe alignment with compiled binding plans."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, cast
from uuid import uuid4

import pytest
from pydantic import BaseModel, ConfigDict
from starlette.requests import Request

from bustan.common.types import RouteMetadata
from bustan.core.errors import BadRequestException
from bustan.core.module.dynamic import ModuleInstanceKey
from bustan.pipeline.built_in_pipes import (
    DefaultValuePipe,
    ParseArrayPipe,
    ParseBoolPipe,
    ParseEnumPipe,
    ParseFloatPipe,
    ParseIntPipe,
    ParseUUIDPipe,
    ValidationPipe,
)
from bustan.pipeline.context import ExecutionContext, RequestContext
from bustan.platform.http.metadata import ControllerRouteDefinition

if TYPE_CHECKING:
    from bustan.core.ioc.container import Container


class PayloadModel(BaseModel):
    name: str
    admin: bool


class WhitelistPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str


@dataclass(frozen=True, slots=True)
class DataclassPayload:
    name: str


class Status(Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


@pytest.mark.anyio
async def test_validation_mode_changes_behavior_only_through_compiled_context() -> None:
    raw_value = {"name": "Ada", "admin": True}

    auto_context = _parameter_context(annotation=PayloadModel, validation_mode="auto")
    off_context = _parameter_context(annotation=PayloadModel, validation_mode="off")

    validated = await ValidationPipe().transform(raw_value, auto_context)
    bypassed = await ValidationPipe().transform(raw_value, off_context)

    assert isinstance(validated, PayloadModel)
    assert bypassed == raw_value


@pytest.mark.anyio
async def test_validation_errors_include_structured_parameter_metadata() -> None:
    context = _parameter_context(annotation=PayloadModel, name="payload", source="body")

    with pytest.raises(BadRequestException) as exc_info:
        await ValidationPipe().transform({"name": "Ada"}, context)

    assert exc_info.value.field == "payload"
    assert exc_info.value.source == "body"
    assert "admin" in exc_info.value.to_payload()["detail"]
    assert "admin" in exc_info.value.to_payload()["reason"]


@pytest.mark.anyio
async def test_parse_scalar_pipes_cover_success_and_error_paths() -> None:
    context = _parameter_context(annotation=str, name="value", source="query")

    assert await ParseIntPipe().transform("7", context) == 7
    assert await ParseFloatPipe().transform("7.5", context) == 7.5
    assert await ParseBoolPipe().transform("yes", context) is True
    assert await ParseBoolPipe().transform("off", context) is False
    assert await ParseUUIDPipe().transform(str(uuid4()), context)

    with pytest.raises(BadRequestException, match="integer expected"):
        await ParseIntPipe().transform("nope", context)

    with pytest.raises(BadRequestException, match="float expected"):
        await ParseFloatPipe().transform("nope", context)

    with pytest.raises(BadRequestException, match="boolean expected"):
        await ParseBoolPipe().transform("maybe", context)

    with pytest.raises(BadRequestException, match="UUID expected"):
        await ParseUUIDPipe().transform("invalid-uuid", context)


@pytest.mark.anyio
async def test_parse_array_enum_and_default_pipes_cover_branching_behavior() -> None:
    context = _parameter_context(annotation=str, name="status", source="query")

    assert await ParseArrayPipe().transform("a,b,c", context) == ["a", "b", "c"]
    assert await ParseArrayPipe(separator="|").transform("a|b", context) == ["a", "b"]
    assert await ParseArrayPipe().transform([1, "two"], context) == ["1", "two"]

    enum_pipe = ParseEnumPipe(Status)
    assert await enum_pipe.transform(Status.ACTIVE, context) is Status.ACTIVE
    assert await enum_pipe.transform("active", context) is Status.ACTIVE
    assert await enum_pipe.transform("INACTIVE", context) is Status.INACTIVE

    with pytest.raises(BadRequestException, match="must be one of"):
        await enum_pipe.transform("pending", context)

    default_pipe = DefaultValuePipe("fallback")
    assert await default_pipe.transform(None, context) == "fallback"
    assert await default_pipe.transform("value", context) == "value"


@pytest.mark.anyio
async def test_validation_pipe_short_circuits_for_non_model_inputs_and_whitelist_mode() -> None:
    raw_value = {"name": "Ada", "extra": "ignored"}

    no_metatype_context = _parameter_context(annotation=list[str])
    dataclass_context = _parameter_context(annotation=DataclassPayload)
    non_model_context = _parameter_context(annotation=str)
    whitelist_context = _parameter_context(annotation=WhitelistPayload)

    assert await ValidationPipe().transform(raw_value, no_metatype_context) == raw_value
    assert await ValidationPipe().transform(raw_value, dataclass_context) == raw_value
    assert await ValidationPipe().transform(raw_value, non_model_context) == raw_value

    validated = await ValidationPipe(whitelist=True).transform(raw_value, whitelist_context)

    assert isinstance(validated, WhitelistPayload)
    assert validated.model_dump() == {"name": "Ada"}


def _parameter_context(
    *,
    annotation: object,
    name: str = "value",
    source: str = "body",
    validation_mode: str = "auto",
) -> ExecutionContext:
    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    request = Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
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
            route=RouteMetadata(method="POST", path="/", name="test"),
        ),
        container=cast("Container", object()),
    )
    return request_context.with_parameter(
        name=name,
        source=source,
        annotation=annotation,
        value=None,
        validation_mode=validation_mode,
    )


def _handler() -> None:
    return None