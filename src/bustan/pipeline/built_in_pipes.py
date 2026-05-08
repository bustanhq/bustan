"""Built-in validation and coercion pipes."""

from __future__ import annotations

from dataclasses import is_dataclass
from enum import Enum
from typing import Any
from uuid import UUID

from ..core.errors import BadRequestException
from .context import ExecutionContext
from .pipes import Pipe

_TRUTHY = {"true", "1", "yes", "on"}
_FALSY = {"false", "0", "no", "off"}


class ParseIntPipe(Pipe):
    """Convert a parameter value into an integer."""

    async def transform(self, value: object, context: ExecutionContext) -> int:
        try:
            return int(str(value))
        except (TypeError, ValueError) as exc:
            raise BadRequestException(
                "Validation failed (integer expected)",
                field=context.parameter_name,
            ) from exc


class ParseFloatPipe(Pipe):
    """Convert a parameter value into a float."""

    async def transform(self, value: object, context: ExecutionContext) -> float:
        try:
            return float(str(value))
        except (TypeError, ValueError) as exc:
            raise BadRequestException(
                "Validation failed (float expected)",
                field=context.parameter_name,
            ) from exc


class ParseBoolPipe(Pipe):
    """Convert a parameter value into a boolean."""

    async def transform(self, value: object, context: ExecutionContext) -> bool:
        normalized = str(value).strip().lower()
        if normalized in _TRUTHY:
            return True
        if normalized in _FALSY:
            return False
        raise BadRequestException(
            "Validation failed (boolean expected)",
            field=context.parameter_name,
        )


class ParseUUIDPipe(Pipe):
    """Convert a parameter value into a UUID instance."""

    async def transform(self, value: object, context: ExecutionContext) -> UUID:
        try:
            return UUID(str(value))
        except (TypeError, ValueError) as exc:
            raise BadRequestException(
                "Validation failed (UUID expected)",
                field=context.parameter_name,
            ) from exc


class ParseArrayPipe(Pipe):
    """Convert delimited strings into a list of strings."""

    def __init__(self, *, separator: str = ",") -> None:
        self.separator = separator

    async def transform(self, value: object, context: ExecutionContext) -> list[str]:
        if isinstance(value, list):
            return [str(item) for item in value]
        return [item for item in str(value).split(self.separator) if item]


class ParseEnumPipe(Pipe):
    """Resolve a raw value to an Enum member."""

    def __init__(self, enum_type: type[Enum]) -> None:
        self.enum_type = enum_type

    async def transform(self, value: object, context: ExecutionContext) -> Enum:
        for member in self.enum_type:
            if value == member or value == member.value or value == member.name:
                return member
        raise BadRequestException(
            f"Validation failed (must be one of {[member.value for member in self.enum_type]})",
            field=context.parameter_name,
        )


class DefaultValuePipe(Pipe):
    """Apply a default when the bound value is missing."""

    def __init__(self, default: Any) -> None:
        self.default = default

    async def transform(self, value: object, context: ExecutionContext) -> object:
        if value is None:
            return self.default
        return value


class ValidationPipe(Pipe):
    """Validate body payloads with Pydantic models when available."""

    def __init__(self, *, whitelist: bool = False) -> None:
        self.whitelist = whitelist

    async def transform(self, value: object, context: ExecutionContext) -> object:
        if context.validation_mode == "off":
            return value

        metatype = context.metatype
        if metatype is None:
            return value

        if is_dataclass(metatype):
            return value

        try:
            from pydantic import BaseModel
        except ImportError:
            return value

        if not isinstance(metatype, type) or not issubclass(metatype, BaseModel):
            return value

        try:
            if self.whitelist:
                validated = metatype.model_validate(value)
                return metatype.model_validate(validated.model_dump())
            return metatype.model_validate(value)
        except Exception as exc:
            raise BadRequestException(
                str(exc),
                field=context.parameter_name,
                source=context.parameter_source,
                reason=str(exc),
            ) from exc
