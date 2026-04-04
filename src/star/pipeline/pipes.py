"""Pipe base class and sequential transformation helpers."""

from __future__ import annotations

import inspect
from dataclasses import replace

from .context import ParameterContext


class Pipe:
    """Base class for parameter transformation and validation."""

    async def transform(self, value: object, context: ParameterContext) -> object:
        """Return the transformed parameter value passed to the handler."""

        return value


async def run_pipes(value: object, context: ParameterContext, pipes: tuple[Pipe, ...]) -> object:
    """Pass a parameter value through each declared pipe in order."""

    current_value = value
    current_context = context

    for pipe in pipes:
        result = pipe.transform(current_value, current_context)
        if inspect.isawaitable(result):
            current_value = await result
        else:
            current_value = result
        current_context = replace(current_context, value=current_value)

    return current_value