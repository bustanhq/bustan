"""Bustan – A dependency injection framework for building modular Starlette applications."""

from __future__ import annotations

import importlib.metadata

# Metadata
__version__ = importlib.metadata.version("bustan")

# Common Decorators
from .common.decorators.injectable import Injectable
from .common.decorators.controller import Controller
from .common.decorators.route import Get, Post, Put, Patch, Delete
from .common.decorators.parameter import (
    Body,
    Cookies,
    Header,
    HostParam,
    Ip,
    Param,
    Query,
    UploadedFile,
    UploadedFiles,
)
from .common.types import ProviderScope as Scope

# Core Module System
from .core.module.decorators import Module
from .core.module.dynamic import DynamicModule
from .core.module.builder import ConfigurableModuleBuilder

# Core IoC System
from .core.ioc.tokens import (
    APP_FILTER,
    APP_GUARD,
    APP_INTERCEPTOR,
    APP_PIPE,
    InjectionToken,
)
from .core.ioc.scopes import DurableProvider

# Pipeline Components
from .pipeline import (
    DefaultValuePipe,
    ExceptionFilter,
    Guard,
    Interceptor,
    ParseArrayPipe,
    ParseBoolPipe,
    ParseEnumPipe,
    ParseFloatPipe,
    ParseIntPipe,
    ParseUUIDPipe,
    Pipe,
    ValidationPipe,
)
from .pipeline.decorators import UseFilters, UseGuards, UseInterceptors, UsePipes
from .pipeline.middleware import Middleware, MiddlewareConsumer

# Application Wrapper
from .app.application import Application, ApplicationContext
from .app.bootstrap import create_app, create_app_context
from .platform.http.versioning import VERSION_NEUTRAL, VersioningOptions, VersioningType
from .config import ConfigModule, ConfigService
from .logger import LogLevel, Logger, LoggerService
from .openapi import (
    ApiBearerAuth,
    ApiBody,
    ApiOperation,
    ApiParam,
    ApiQuery,
    ApiResponse,
    ApiTags,
    DocumentBuilder,
    SwaggerModule,
    SwaggerOptions,
)
from .security import CorsOptions, SkipThrottle, ThrottlerGuard, ThrottlerModule, ThrottlerStorage

# Lifecycle Protocols
from .core.lifecycle.hooks import (
    OnApplicationBootstrap,
    OnApplicationShutdown,
    OnModuleDestroy,
    OnModuleInit,
)

# Core Errors
from .core.errors import (
    BadRequestException,
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
    "APP_FILTER",
    "APP_GUARD",
    "APP_INTERCEPTOR",
    "APP_PIPE",
    "ApiBearerAuth",
    "ApiBody",
    "ApiOperation",
    "ApiParam",
    "ApiQuery",
    "ApiResponse",
    "ApiTags",
    "BadRequestException",
    "Body",
    "Cookies",
    "create_app",
    "create_app_context",
    "BustanError",
    "Controller",
    "Delete",
    "DurableProvider",
    "DynamicModule",
    "DocumentBuilder",
    "ExceptionFilter",
    "ExportViolationError",
    "Get",
    "Guard",
    "GuardRejectedError",
    "Header",
    "HostParam",
    "Injectable",
    "InjectionToken",
    "Interceptor",
    "InvalidControllerError",
    "InvalidModuleError",
    "InvalidPipelineError",
    "InvalidProviderError",
    "LifecycleError",
    "LogLevel",
    "Logger",
    "LoggerService",
    "Middleware",
    "MiddlewareConsumer",
    "Module",
    "ModuleCycleError",
    "OnApplicationBootstrap",
    "OnApplicationShutdown",
    "OnModuleDestroy",
    "OnModuleInit",
    "Param",
    "ParameterBindingError",
    "ParseArrayPipe",
    "ParseBoolPipe",
    "ParseEnumPipe",
    "ParseFloatPipe",
    "ParseIntPipe",
    "ParseUUIDPipe",
    "Patch",
    "Pipe",
    "Post",
    "ProviderResolutionError",
    "Put",
    "Query",
    "RouteDefinitionError",
    "Scope",
    "DefaultValuePipe",
    "UploadedFile",
    "UploadedFiles",
    "ValidationPipe",
    "Ip",
    "VERSION_NEUTRAL",
    "VersioningOptions",
    "VersioningType",
    "ConfigurableModuleBuilder",
    "ConfigModule",
    "ConfigService",
    "CorsOptions",
    "SkipThrottle",
    "SwaggerModule",
    "SwaggerOptions",
    "ThrottlerGuard",
    "ThrottlerModule",
    "ThrottlerStorage",
    "UseFilters",
    "UseGuards",
    "UseInterceptors",
    "UsePipes",
)
