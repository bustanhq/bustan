"""Redirect for platform-specific response coercion."""

from .adapters.starlette import coerce_response

__all__ = ["coerce_response"]
