"""OpenAPI schema generation from compiled route contracts."""

from __future__ import annotations

import copy
from enum import Enum
from types import FunctionType
from types import NoneType, UnionType
from typing import Any, Union, cast, get_args, get_origin
from uuid import UUID

from ..platform.http.compiler import RouteContract
from ..platform.http.params import HandlerBindingPlan, ParameterSource
from .decorators import (
    OPENAPI_BODY_ATTR,
    OPENAPI_OPERATION_ATTR,
    OPENAPI_PARAMS_ATTR,
    OPENAPI_RESPONSES_ATTR,
    OPENAPI_SECURITY_ATTR,
    OPENAPI_TAGS_ATTR,
)


def generate_schema(route_contracts: tuple[RouteContract, ...], document: dict[str, Any]) -> dict[str, Any]:
    """Generate an OpenAPI document from compiled route contracts."""

    schema = copy.deepcopy(document)
    components = cast(dict[str, Any], schema.setdefault("components", {}))
    components.setdefault("schemas", {})
    components.setdefault("securitySchemes", {})
    paths = cast(dict[str, Any], schema.setdefault("paths", {}))

    for route_contract in route_contracts:
        path_item = cast(dict[str, Any], paths.setdefault(route_contract.path, {}))
        path_item[route_contract.method.lower()] = _build_operation(route_contract, components)

    return schema


def _build_operation(
    route_contract: RouteContract,
    components: dict[str, Any],
) -> dict[str, Any]:
    handler = route_contract.handler
    operation: dict[str, Any] = {
        "operationId": f"{route_contract.controller_cls.__name__}.{route_contract.handler_name}",
        "responses": {},
    }
    controller_tags = list(getattr(route_contract.controller_cls, OPENAPI_TAGS_ATTR, ()))
    if controller_tags:
        operation["tags"] = controller_tags

    operation_metadata = getattr(handler, OPENAPI_OPERATION_ATTR, None)
    if isinstance(operation_metadata, dict):
        if operation_metadata.get("summary"):
            operation["summary"] = operation_metadata["summary"]
        if operation_metadata.get("description"):
            operation["description"] = operation_metadata["description"]

    controller_security = list(getattr(route_contract.controller_cls, OPENAPI_SECURITY_ATTR, ()))
    security = list(controller_security)
    security.extend(getattr(handler, OPENAPI_SECURITY_ATTR, ()))
    if security:
        operation["security"] = security

    parameters = _build_parameters(route_contract.binding_plan, route_contract.method, handler)
    if parameters:
        operation["parameters"] = parameters

    request_body = _build_request_body(route_contract.binding_plan, handler, components)
    if request_body is not None:
        operation["requestBody"] = request_body

    responses = _build_responses(route_contract, components)
    if responses:
        operation["responses"] = responses

    return operation


def _build_parameters(
    binding_plan: HandlerBindingPlan,
    method: str,
    handler: FunctionType,
) -> list[dict[str, Any]]:
    parameters: dict[tuple[str, str], dict[str, Any]] = {}

    for binding in binding_plan.parameters:
        if binding.source is ParameterSource.PATH:
            name = binding.alias or binding.name
            parameters[("path", name)] = {
                "name": name,
                "in": "path",
                "required": True,
                "schema": _annotation_to_schema(binding.annotation),
            }
        elif binding.source is ParameterSource.QUERY:
            name = binding.alias or binding.name
            parameters[("query", name)] = {
                "name": name,
                "in": "query",
                "required": not binding.has_default,
                "schema": _annotation_to_schema(binding.annotation),
            }
        elif binding.source is ParameterSource.HEADER:
            name = binding.alias or binding.name
            parameters[("header", name)] = {
                "name": name,
                "in": "header",
                "required": not binding.has_default,
                "schema": _annotation_to_schema(binding.annotation),
            }
        elif binding.source is ParameterSource.INFERRED and method in {"GET", "DELETE"}:
            if _is_pydantic_model(binding.annotation):
                continue
            name = binding.alias or binding.name
            parameters[("query", name)] = {
                "name": name,
                "in": "query",
                "required": not binding.has_default,
                "schema": _annotation_to_schema(binding.annotation),
            }

    for explicit in getattr(handler, OPENAPI_PARAMS_ATTR, ()):
        name = explicit["name"]
        location = explicit["in"]
        entry = parameters.get((location, name), {"name": name, "in": location})
        entry["required"] = explicit["required"]
        if explicit.get("description"):
            entry["description"] = explicit["description"]
        if location == "query" and "type" in explicit:
            entry["schema"] = _annotation_to_schema(explicit["type"])
        entry.setdefault("schema", {"type": "string"})
        parameters[(location, name)] = entry

    return list(parameters.values())


def _build_request_body(
    binding_plan: HandlerBindingPlan,
    handler: FunctionType,
    components: dict[str, Any],
) -> dict[str, Any] | None:
    explicit_body = getattr(handler, OPENAPI_BODY_ATTR, None)
    if isinstance(explicit_body, dict):
        schema = _schema_for_annotation(explicit_body["type"], components)
        request_body: dict[str, Any] = {
            "content": {"application/json": {"schema": schema}},
            "required": True,
        }
        if explicit_body.get("description"):
            request_body["description"] = explicit_body["description"]
        return request_body

    if binding_plan.body_model is not None:
        return {
            "content": {
                "application/json": {
                    "schema": _schema_for_annotation(binding_plan.body_model, components)
                }
            },
            "required": True,
        }

    for binding in binding_plan.parameters:
        if binding.source is ParameterSource.BODY or (
            binding.source is ParameterSource.INFERRED and _is_pydantic_model(binding.annotation)
        ):
            return {
                "content": {
                    "application/json": {
                        "schema": _schema_for_annotation(binding.annotation, components)
                    }
                },
                "required": not binding.has_default,
            }
        if binding.source is ParameterSource.FILE:
            return {
                "content": {
                    "multipart/form-data": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                (binding.alias or binding.name): {
                                    "type": "string",
                                    "format": "binary",
                                }
                            },
                            "required": [binding.alias or binding.name],
                        }
                    }
                }
            }
        if binding.source is ParameterSource.FILES:
            return {
                "content": {
                    "multipart/form-data": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                (binding.alias or binding.name): {
                                    "type": "array",
                                    "items": {"type": "string", "format": "binary"},
                                }
                            },
                            "required": [binding.alias or binding.name],
                        }
                    }
                }
            }

    return None


def _build_responses(route_contract: RouteContract, components: dict[str, Any]) -> dict[str, Any]:
    handler = route_contract.handler
    responses = getattr(handler, OPENAPI_RESPONSES_ATTR, ())
    if responses:
        rendered: dict[str, Any] = {}
        for response in responses:
            entry: dict[str, Any] = {"description": response["description"] or "Successful Response"}
            if response.get("schema") is not None:
                entry["content"] = {
                    "application/json": {
                        "schema": _schema_for_annotation(response["schema"], components)
                    }
                }
            rendered[str(response["status"])] = entry
        return rendered

    rendered: dict[str, Any] = {}
    for declared_response in route_contract.response_plan.declared_responses:
        entry: dict[str, Any] = {
            "description": declared_response.description or "Successful Response"
        }
        if declared_response.schema is not None:
            entry["content"] = {
                "application/json": {
                    "schema": _schema_for_annotation(declared_response.schema, components)
                }
            }
        rendered[str(declared_response.status)] = entry
    return rendered


def _schema_for_annotation(annotation: object, components: dict[str, Any]) -> dict[str, Any]:
    if _is_pydantic_model(annotation):
        return _register_model_schema(annotation, components)
    return _annotation_to_schema(annotation)


def _register_model_schema(annotation: object, components: dict[str, Any]) -> dict[str, Any]:
    schemas = cast(dict[str, Any], components.setdefault("schemas", {}))
    assert isinstance(annotation, type)
    name = annotation.__name__
    if name not in schemas:
        model_schema = cast(
            dict[str, Any],
            cast(Any, annotation).model_json_schema(
                ref_template="#/components/schemas/{model}"
            ),
        )
        defs = model_schema.pop("$defs", {})
        if isinstance(defs, dict):
            for definition_name, definition in defs.items():
                schemas.setdefault(definition_name, definition)
        schemas[name] = model_schema
    return {"$ref": f"#/components/schemas/{name}"}


def _annotation_to_schema(annotation: object) -> dict[str, Any]:
    if annotation in (str, Any, object):
        return {"type": "string"}
    if annotation is int:
        return {"type": "integer"}
    if annotation is float:
        return {"type": "number"}
    if annotation is bool:
        return {"type": "boolean"}
    if annotation is NoneType:
        return {"type": "null"}
    if annotation is UUID:
        return {"type": "string", "format": "uuid"}
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        values = [member.value for member in annotation]
        value_type = "string" if all(isinstance(value, str) for value in values) else "integer"
        return {"type": value_type, "enum": values}

    origin = get_origin(annotation)
    if origin is list:
        (item_type,) = get_args(annotation) or (str,)
        return {"type": "array", "items": _annotation_to_schema(item_type)}
    if origin in {dict, tuple, set}:
        return {"type": "object"}
    if origin in {UnionType, Union}:
        args = [arg for arg in get_args(annotation) if arg is not NoneType]
        if len(args) == 1 and len(args) != len(get_args(annotation)):
            schema = _annotation_to_schema(args[0])
            schema["nullable"] = True
            return schema
        return {"anyOf": [_annotation_to_schema(argument) for argument in get_args(annotation)]}

    return {"type": "object"}


def _is_pydantic_model(annotation: object) -> bool:
    return isinstance(annotation, type) and hasattr(annotation, "model_json_schema")
