"""Unit tests for OpenAPI schema generation."""

from __future__ import annotations

from typing import Annotated, Any, cast

from pydantic import BaseModel

from bustan import Body, Controller, Get, Module, Param, Post, Query
from bustan.openapi import (
    ApiBody,
    ApiOperation,
    ApiParam,
    ApiQuery,
    ApiResponse,
    ApiTags,
    DocumentBuilder,
)
from bustan.openapi.schema_builder import generate_schema
from bustan.core.module.graph import build_module_graph


class CatDto(BaseModel):
    name: str


def test_document_builder_produces_openapi_document() -> None:
    document = cast(
        dict[str, Any],
        DocumentBuilder().set_title("Test").set_version("1.0").add_bearer_auth().build(),
    )

    assert document["openapi"] == "3.1.0"
    assert document["info"]["title"] == "Test"
    assert "bearer" in document["components"]["securitySchemes"]


def test_schema_generation_uses_decorator_metadata() -> None:
    @ApiTags("cats")
    @Controller("/cats")
    class CatsController:
        @ApiOperation(summary="Get cat", description="Returns a cat")
        @ApiResponse(status=200, description="Cat found")
        @ApiParam(name="id", description="The cat ID")
        @ApiQuery(name="limit", description="Result limit", required=False, type=int)
        @Get("/{id}")
        def get_cat(
            self,
            id: Annotated[int, Param],
            limit: Annotated[int | None, Query] = None,
        ) -> dict[str, str]:
            return {"status": "ok"}

        @ApiBody(type=CatDto, description="Cat payload")
        @Post("/")
        def create_cat(self, payload: Annotated[CatDto, Body]) -> dict[str, str]:
            return {"status": "created"}

    @Module(controllers=[CatsController])
    class AppModule:
        pass

    schema = cast(
        dict[str, Any],
        generate_schema(
            build_module_graph(AppModule),
            DocumentBuilder().set_title("Cats").set_version("1.0").build(),
        ),
    )

    get_operation = schema["paths"]["/cats/{id}"]["get"]
    assert get_operation["tags"] == ["cats"]
    assert get_operation["summary"] == "Get cat"
    assert get_operation["description"] == "Returns a cat"
    assert get_operation["responses"]["200"]["description"] == "Cat found"
    assert any(
        parameter["name"] == "id" and parameter["description"] == "The cat ID"
        for parameter in get_operation["parameters"]
    )
    assert any(
        parameter["name"] == "limit"
        and parameter["in"] == "query"
        and parameter["schema"]["type"] == "integer"
        for parameter in get_operation["parameters"]
    )

    post_operation = schema["paths"]["/cats"]["post"]
    assert post_operation["requestBody"]["description"] == "Cat payload"
    assert (
        post_operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/CatDto"
    )


def test_schema_generation_infers_pydantic_request_bodies() -> None:
    @Controller("/cats")
    class CatsController:
        @Post("/")
        def create_cat(self, payload: CatDto) -> dict[str, str]:
            return {"status": "created"}

    @Module(controllers=[CatsController])
    class AppModule:
        pass

    schema = cast(
        dict[str, Any],
        generate_schema(build_module_graph(AppModule), DocumentBuilder().build()),
    )

    request_body = schema["paths"]["/cats"]["post"]["requestBody"]
    assert request_body["content"]["application/json"]["schema"]["$ref"] == "#/components/schemas/CatDto"


def test_schema_generation_infers_path_parameters_from_routes() -> None:
    @Controller("/items")
    class ItemsController:
        @Get("/{item_id}")
        def show(self, item_id: int) -> dict[str, str]:
            return {"status": "ok"}

    @Module(controllers=[ItemsController])
    class AppModule:
        pass

    schema = cast(
        dict[str, Any],
        generate_schema(build_module_graph(AppModule), DocumentBuilder().build()),
    )

    parameters = schema["paths"]["/items/{item_id}"]["get"]["parameters"]
    assert parameters == [
        {
            "name": "item_id",
            "in": "path",
            "required": True,
            "schema": {"type": "integer"},
        }
    ]
