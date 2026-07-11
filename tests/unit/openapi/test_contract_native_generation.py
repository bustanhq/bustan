"""Unit tests for contract-native OpenAPI generation."""

from __future__ import annotations

import inspect
from enum import Enum
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from bustan import (
    ApiBearerAuth,
    ApiOperation,
    ApiParam,
    ApiQuery,
    ApiResponse,
    Controller,
    Get,
    Module,
    Post,
)
from bustan.core.ioc.container import build_container
from bustan.core.module.graph import build_module_graph
from bustan.openapi import DocumentBuilder
from bustan.openapi.schema_builder import (
    _annotation_to_schema,
    _build_parameters,
    _build_request_body,
    _build_responses,
    _register_model_schema,
    generate_schema,
)
from bustan.platform.http.compiler import DeclaredResponse, ResponsePlan, compile_route_contracts
from bustan.platform.http.params import (
    HandlerBindingPlan,
    ParameterBinding,
    ParameterBindingMode,
    ParameterSource,
    ValidationMode,
)


class CatPayload(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": {"name": "Milo"}})

    name: str = Field(description="The cat name", examples=["Milo"])


def test_operation_metadata_comes_from_compiled_contracts() -> None:
    @Controller("/cats")
    class CatsController:
        @ApiOperation(summary="Read cat", description="Returns one cat")
        @ApiResponse(status=200, description="Cat found")
        @Get("/{cat_id}")
        def read_cat(self, cat_id: int) -> dict[str, str]:
            return {"id": str(cat_id)}

    @Module(controllers=[CatsController])
    class AppModule:
        pass

    graph = build_module_graph(AppModule)
    schema = generate_schema(
        compile_route_contracts(graph, build_container(graph)),
        DocumentBuilder().build(),
    )

    operation = schema["paths"]["/cats/{cat_id}"]["get"]
    assert operation["operationId"] == "CatsController.read_cat"
    assert operation["summary"] == "Read cat"
    assert operation["description"] == "Returns one cat"
    assert operation["responses"]["200"]["description"] == "Cat found"


def test_dto_descriptions_and_examples_appear_in_generated_schema() -> None:
    @Controller("/cats")
    class CatsController:
        @Post("/")
        def create_cat(self, payload: CatPayload) -> dict[str, str]:
            return {"name": payload.name}

    @Module(controllers=[CatsController])
    class AppModule:
        pass

    graph = build_module_graph(AppModule)
    schema = generate_schema(
        compile_route_contracts(graph, build_container(graph)),
        DocumentBuilder().build(),
    )

    cat_schema = schema["components"]["schemas"]["CatPayload"]
    assert cat_schema["example"] == {"name": "Milo"}
    assert cat_schema["properties"]["name"]["description"] == "The cat name"
    assert cat_schema["properties"]["name"]["examples"] == ["Milo"]


def test_generation_order_is_deterministic() -> None:
    @Controller("/zeta")
    class ZetaController:
        @Get("/")
        def read_zeta(self) -> dict[str, str]:
            return {"controller": "zeta"}

    @Controller("/alpha")
    class AlphaController:
        @Get("/")
        def read_alpha(self) -> dict[str, str]:
            return {"controller": "alpha"}

    @Module(controllers=[ZetaController, AlphaController])
    class AppModule:
        pass

    graph = build_module_graph(AppModule)
    route_contracts = compile_route_contracts(graph, build_container(graph))

    first = generate_schema(route_contracts, DocumentBuilder().build())
    second = generate_schema(route_contracts, DocumentBuilder().build())

    assert list(first["paths"].keys()) == ["/zeta", "/alpha"]
    assert first == second


def test_schema_generation_merges_controller_and_handler_security() -> None:
    @ApiBearerAuth("controller")
    @Controller("/secure")
    class SecureController:
        @ApiBearerAuth("handler")
        @Get("/")
        def read_secure(self) -> dict[str, str]:
            return {"status": "ok"}

    @Module(controllers=[SecureController])
    class AppModule:
        pass

    graph = build_module_graph(AppModule)
    schema = generate_schema(
        compile_route_contracts(graph, build_container(graph)),
        DocumentBuilder().build(),
    )

    assert schema["paths"]["/secure"]["get"]["security"] == [
        {"controller": []},
        {"handler": []},
    ]


def test_schema_builder_helpers_cover_annotations_models_parameters_and_responses() -> None:
    class StringState(Enum):
        OPEN = "open"

    class IntState(Enum):
        OK = 200

    class InnerPayload(BaseModel):
        id: int

    class OuterPayload(BaseModel):
        inner: InnerPayload

    assert _annotation_to_schema(UUID) == {"type": "string", "format": "uuid"}
    assert _annotation_to_schema(float) == {"type": "number"}
    assert _annotation_to_schema(bool) == {"type": "boolean"}
    assert _annotation_to_schema(type(None)) == {"type": "null"}
    assert _annotation_to_schema(StringState) == {"type": "string", "enum": ["open"]}
    assert _annotation_to_schema(IntState) == {"type": "integer", "enum": [200]}
    assert _annotation_to_schema(list[int]) == {
        "type": "array",
        "items": {"type": "integer"},
    }
    assert _annotation_to_schema(dict[str, str]) == {"type": "object"}
    assert _annotation_to_schema(tuple[int, str]) == {"type": "object"}
    assert _annotation_to_schema(set[str]) == {"type": "object"}
    assert _annotation_to_schema(int | None) == {"type": "integer", "nullable": True}
    assert _annotation_to_schema(str | int) == {
        "anyOf": [{"type": "string"}, {"type": "integer"}]
    }
    assert _annotation_to_schema(type("CustomType", (), {})) == {"type": "object"}

    components: dict[str, object] = {"schemas": {}}
    assert _register_model_schema(OuterPayload, components) == {
        "$ref": "#/components/schemas/OuterPayload"
    }
    assert _register_model_schema(OuterPayload, components) == {
        "$ref": "#/components/schemas/OuterPayload"
    }
    assert "OuterPayload" in components["schemas"]
    assert "InnerPayload" in components["schemas"]

    @ApiParam(name="slug", description="Stable slug")
    @ApiQuery(name="search", description="Search term", required=False, type=int)
    def documented_handler() -> None:
        return None

    parameters = _build_parameters(
        _binding_plan(
            _binding("id", ParameterSource.PATH, int),
            _binding("token", ParameterSource.HEADER, str, has_default=True, alias="x-token"),
            _binding("search", ParameterSource.INFERRED, int, has_default=True),
            _binding("payload", ParameterSource.INFERRED, OuterPayload),
        ),
        "GET",
        documented_handler,
    )

    assert any(
        parameter == {
            "name": "id",
            "in": "path",
            "required": True,
            "schema": {"type": "integer"},
        }
        for parameter in parameters
    )
    assert any(
        parameter["name"] == "x-token"
        and parameter["in"] == "header"
        and parameter["required"] is False
        for parameter in parameters
    )
    assert any(
        parameter["name"] == "search"
        and parameter["description"] == "Search term"
        and parameter["schema"] == {"type": "integer"}
        for parameter in parameters
    )
    assert any(
        parameter["name"] == "slug"
        and parameter["schema"] == {"type": "string"}
        for parameter in parameters
    )
    assert all(parameter["name"] != "payload" for parameter in parameters)

    request_components: dict[str, object] = {"schemas": {}}
    assert _build_request_body(
        _binding_plan(body_model=CatPayload),
        documented_handler,
        request_components,
    ) == {
        "content": {
            "application/json": {
                "schema": {"$ref": "#/components/schemas/CatPayload"}
            }
        },
        "required": True,
    }
    file_body = _build_request_body(
        _binding_plan(_binding("upload", ParameterSource.FILE, bytes)),
        documented_handler,
        {"schemas": {}},
    )
    files_body = _build_request_body(
        _binding_plan(_binding("uploads", ParameterSource.FILES, list[bytes])),
        documented_handler,
        {"schemas": {}},
    )
    inferred_body = _build_request_body(
        _binding_plan(_binding("payload", ParameterSource.BODY, OuterPayload, has_default=True)),
        documented_handler,
        {"schemas": {}},
    )

    assert file_body == {
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "properties": {
                        "upload": {"type": "string", "format": "binary"}
                    },
                    "required": ["upload"],
                }
            }
        }
    }
    assert files_body == {
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "properties": {
                        "uploads": {
                            "type": "array",
                            "items": {"type": "string", "format": "binary"},
                        }
                    },
                    "required": ["uploads"],
                }
            }
        }
    }
    assert inferred_body == {
        "content": {
            "application/json": {
                "schema": {"$ref": "#/components/schemas/OuterPayload"}
            }
        },
        "required": False,
    }

    @ApiResponse(status=202)
    def response_handler() -> None:
        return None

    explicit_responses = _build_responses(
        cast(
            Any,
            SimpleNamespace(
                handler=response_handler,
                response_plan=ResponsePlan(declared_type=None),
            ),
        ),
        {"schemas": {}},
    )

    declared_responses = _build_responses(
        cast(
            Any,
            SimpleNamespace(
                handler=documented_handler,
                response_plan=ResponsePlan(
                    declared_type=None,
                    declared_responses=(
                        DeclaredResponse(status=201, schema=CatPayload),
                        DeclaredResponse(status=204, description="No Content"),
                    ),
                ),
            ),
        ),
        {"schemas": {}},
    )

    assert declared_responses["201"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/CatPayload"
    }
    assert declared_responses["204"] == {"description": "No Content"}
    assert explicit_responses == {"202": {"description": "Successful Response"}}


def _binding(
    name: str,
    source: ParameterSource,
    annotation: object,
    *,
    has_default: bool = False,
    alias: str | None = None,
) -> ParameterBinding:
    return ParameterBinding(
        name=name,
        kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
        source=source,
        annotation=annotation,
        has_default=has_default,
        default=None,
        alias=alias,
    )


def _binding_plan(
    *bindings: ParameterBinding,
    body_model: type[object] | None = None,
) -> HandlerBindingPlan:
    return HandlerBindingPlan(
        controller=object,
        handler_name="handler",
        parameters=bindings,
        inferred_parameter_names=(),
        mode=ParameterBindingMode.INFER,
        body_model=body_model,
        validation_mode=ValidationMode.AUTO,
    )