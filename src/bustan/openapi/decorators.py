"""OpenAPI metadata decorators."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

DecoratedT = TypeVar("DecoratedT")

OPENAPI_TAGS_ATTR = "__bustan_openapi_tags__"
OPENAPI_OPERATION_ATTR = "__bustan_openapi_operation__"
OPENAPI_RESPONSES_ATTR = "__bustan_openapi_responses__"
OPENAPI_BODY_ATTR = "__bustan_openapi_body__"
OPENAPI_PARAMS_ATTR = "__bustan_openapi_params__"
OPENAPI_SECURITY_ATTR = "__bustan_openapi_security__"


def ApiTags(*tags: str) -> Callable[[DecoratedT], DecoratedT]:
    def decorate(target: DecoratedT) -> DecoratedT:
        setattr(target, OPENAPI_TAGS_ATTR, tuple(tags))
        return target

    return decorate


def ApiOperation(*, summary: str = "", description: str = "") -> Callable[[DecoratedT], DecoratedT]:
    def decorate(target: DecoratedT) -> DecoratedT:
        setattr(
            target,
            OPENAPI_OPERATION_ATTR,
            {"summary": summary, "description": description},
        )
        return target

    return decorate


def ApiResponse(
    *, status: int, description: str = "", schema: type[object] | None = None
) -> Callable[[DecoratedT], DecoratedT]:
    def decorate(target: DecoratedT) -> DecoratedT:
        existing = list(getattr(target, OPENAPI_RESPONSES_ATTR, ()))
        existing.append({"status": status, "description": description, "schema": schema})
        setattr(target, OPENAPI_RESPONSES_ATTR, tuple(existing))
        return target

    return decorate


def ApiBody(*, type: type[object], description: str = "") -> Callable[[DecoratedT], DecoratedT]:
    def decorate(target: DecoratedT) -> DecoratedT:
        setattr(target, OPENAPI_BODY_ATTR, {"type": type, "description": description})
        return target

    return decorate


def ApiParam(
    *, name: str, description: str = "", required: bool = True
) -> Callable[[DecoratedT], DecoratedT]:
    def decorate(target: DecoratedT) -> DecoratedT:
        existing = list(getattr(target, OPENAPI_PARAMS_ATTR, ()))
        existing.append(
            {"in": "path", "name": name, "description": description, "required": required}
        )
        setattr(target, OPENAPI_PARAMS_ATTR, tuple(existing))
        return target

    return decorate


def ApiQuery(
    *,
    name: str,
    description: str = "",
    required: bool = False,
    type: type[object] = str,
) -> Callable[[DecoratedT], DecoratedT]:
    def decorate(target: DecoratedT) -> DecoratedT:
        existing = list(getattr(target, OPENAPI_PARAMS_ATTR, ()))
        existing.append(
            {
                "in": "query",
                "name": name,
                "description": description,
                "required": required,
                "type": type,
            }
        )
        setattr(target, OPENAPI_PARAMS_ATTR, tuple(existing))
        return target

    return decorate


def ApiBearerAuth(name: str = "bearer") -> Callable[[DecoratedT], DecoratedT]:
    def decorate(target: DecoratedT) -> DecoratedT:
        existing = list(getattr(target, OPENAPI_SECURITY_ATTR, ()))
        existing.append({name: []})
        setattr(target, OPENAPI_SECURITY_ATTR, tuple(existing))
        return target

    return decorate
