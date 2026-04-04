"""Supported public API for the star package."""

from ._version import __version__
from .application import bootstrap, create_app
from .decorators import (
    Controller,
    Delete,
    Get,
    Injectable,
    Module,
    Patch,
    Post,
    Put,
    UseFilters,
    UseGuards,
    UseInterceptors,
    UsePipes,
)
from .pipeline import ExceptionFilter, Guard, Interceptor, Pipe

__all__ = (
    "__version__",
    "ExceptionFilter",
    "Guard",
    "Interceptor",
    "Pipe",
    "bootstrap",
    "Controller",
    "create_app",
    "Delete",
    "Get",
    "Injectable",
    "Module",
    "Patch",
    "Post",
    "Put",
    "UseFilters",
    "UseGuards",
    "UseInterceptors",
    "UsePipes",
)
