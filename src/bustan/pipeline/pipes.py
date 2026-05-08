"""Pipe base class and sequential transformation helpers."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable

from .context import ExecutionContext


class Pipe:
    """Base class for parameter transformation and validation."""

    def transform(
        self, value: object, context: ExecutionContext
    ) -> object | Awaitable[object]:
        """Return the transformed parameter value passed to the handler."""

        return value


async def run_pipes(value: object, context: ExecutionContext, pipes: tuple[Pipe, ...]) -> object:
    """Pass a parameter value through each declared pipe in order."""

    pipes = _resolved_pipes(context, pipes)
    current_value = value
    current_context = context

    for pipe in pipes:
        result = pipe.transform(current_value, current_context)
        if inspect.isawaitable(result):
            current_value = await result
        else:
            current_value = result
        current_context = current_context.with_parameter_value(current_value)

    return current_value


def _resolved_pipes(context: ExecutionContext, pipes: tuple[Pipe, ...]) -> tuple[Pipe, ...]:
    if context.validation_mode != "auto":
        return pipes

    if context.parameter_source == "custom" and not context.validate_custom_decorators:
        return pipes

    metatype = context.metatype
    if not _supports_automatic_validation(metatype):
        return pipes

    from .built_in_pipes import ValidationPipe

    if any(isinstance(pipe, ValidationPipe) for pipe in pipes):
        return pipes
    return (*pipes, ValidationPipe())


def _supports_automatic_validation(metatype: type[object] | None) -> bool:
    if metatype is None:
        return False

    try:
        from pydantic import BaseModel
    except ImportError:
        return False

    return issubclass(metatype, BaseModel)
