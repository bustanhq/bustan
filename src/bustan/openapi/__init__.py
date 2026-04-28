"""OpenAPI and Swagger support."""

from __future__ import annotations

from dataclasses import dataclass

from .decorators import (
    ApiBearerAuth,
    ApiBody,
    ApiOperation,
    ApiParam,
    ApiQuery,
    ApiResponse,
    ApiTags,
)
from .document_builder import DocumentBuilder
from .swagger_ui import SwaggerModule


@dataclass(frozen=True, slots=True)
class SwaggerOptions:
    document_builder: DocumentBuilder
    path: str = "/api"
    swagger_ui_path: str | None = None


__all__ = (
    "ApiBearerAuth",
    "ApiBody",
    "ApiOperation",
    "ApiParam",
    "ApiQuery",
    "ApiResponse",
    "ApiTags",
    "DocumentBuilder",
    "SwaggerModule",
    "SwaggerOptions",
)
