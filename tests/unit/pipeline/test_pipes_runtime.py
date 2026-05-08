"""Unit tests for sequential pipe execution helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest
from pydantic import BaseModel
from starlette.requests import Request

from bustan.common.types import RouteMetadata
from bustan.core.module.dynamic import ModuleInstanceKey
from bustan.pipeline.built_in_pipes import ValidationPipe
from bustan.pipeline.context import ExecutionContext, RequestContext
from bustan.pipeline.pipes import Pipe, _supports_automatic_validation, run_pipes
from bustan.platform.http.metadata import ControllerRouteDefinition

if TYPE_CHECKING:
    from bustan.core.ioc.container import Container


class PayloadModel(BaseModel):
    name: str


class SyncPipe(Pipe):
    async def transform(self, value: object, context: ExecutionContext) -> object:
        return f"{value}:sync"


class AsyncPipe(Pipe):
    async def transform(self, value: object, context: ExecutionContext) -> object:
        return f"{value}:async"


class PlainPipe(Pipe):
    def transform(self, value: object, context: ExecutionContext) -> object:
        return f"{value}:plain"


@pytest.mark.anyio
async def test_run_pipes_executes_transformers_in_order() -> None:
    context = _parameter_context(annotation=str)

    result = await run_pipes("value", context, (SyncPipe(), AsyncPipe()))

    assert result == "value:sync:async"


@pytest.mark.anyio
async def test_run_pipes_auto_injects_validation_only_for_auto_pydantic_contexts() -> None:
    auto_context = _parameter_context(annotation=PayloadModel, validation_mode="auto")
    explicit_context = _parameter_context(annotation=PayloadModel, validation_mode="explicit")

    auto_result = await run_pipes({"name": "Ada"}, auto_context, ())
    explicit_result = await run_pipes({"name": "Ada"}, explicit_context, ())
    existing_result = await run_pipes({"name": "Ada"}, auto_context, (ValidationPipe(),))

    assert isinstance(auto_result, PayloadModel)
    assert explicit_result == {"name": "Ada"}
    assert isinstance(existing_result, PayloadModel)


@pytest.mark.anyio
async def test_pipe_helpers_cover_base_transform_and_non_pydantic_support_checks() -> None:
    context = _parameter_context(annotation=str)

    assert Pipe().transform("value", context) == "value"
    assert await run_pipes("value", context, ()) == "value"
    assert await run_pipes("value", context, (PlainPipe(),)) == "value:plain"
    assert not _supports_automatic_validation(None)
    assert not _supports_automatic_validation(str)


def _parameter_context(
    *,
    annotation: object,
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
        name="payload",
        source="body",
        annotation=annotation,
        value=None,
        validation_mode=validation_mode,
    )


def _handler() -> None:
    return None