"""Bustan – A dependency injection framework for building modular Starlette applications."""

from __future__ import annotations

import importlib.metadata

# Metadata
__version__ = importlib.metadata.version("bustan")

# Common Decorators
from .common.decorators.injectable import Injectable
from .common.decorators.controller import Controller
from .common.decorators.route import Get, Post, Put, Patch, Delete
from .common.decorators.parameter import Body, Query, Param, Header

# Core Module System
from .core.module.decorators import Module
from .core.module.dynamic import DynamicModule

# Core IoC System
from .core.ioc.tokens import InjectionToken

# Pipeline Components
from .pipeline import ExceptionFilter, Guard, Interceptor, Pipe
from .pipeline.decorators import UseFilters, UseGuards, UseInterceptors, UsePipes

# Application Wrapper
from .app.application import Application, ApplicationContext
from .app.bootstrap import create_app, create_app_context

# Core Errors
from .core.errors import (
    BustanError,
    ExportViolationError,
    GuardRejectedError,
    InvalidControllerError,
    InvalidModuleError,
    InvalidPipelineError,
    InvalidProviderError,
    LifecycleError,
    ModuleCycleError,
    ParameterBindingError,
    ProviderResolutionError,
    RouteDefinitionError,
)

__all__ = (
    "__version__",
    "Application",
    "ApplicationContext",
    "Body",
    "create_app",
    "create_app_context",
    "BustanError",
    "Controller",
    "Delete",
    "DynamicModule",
    "ExceptionFilter",
    "ExportViolationError",
    "Get",
    "Guard",
    "GuardRejectedError",
    "Header",
    "Injectable",
    "InjectionToken",
    "Interceptor",
    "InvalidControllerError",
    "InvalidModuleError",
    "InvalidPipelineError",
    "InvalidProviderError",
    "LifecycleError",
    "Module",
    "ModuleCycleError",
    "Param",
    "ParameterBindingError",
    "Patch",
    "Pipe",
    "Post",
    "ProviderResolutionError",
    "Put",
    "Query",
    "RouteDefinitionError",
    "UseFilters",
    "UseGuards",
    "UseInterceptors",
    "UsePipes",
)
