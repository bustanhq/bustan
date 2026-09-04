"""Bustan – A dependency injection framework for building modular Starlette applications."""

from __future__ import annotations

import importlib.metadata

# Metadata
__version__ = importlib.metadata.version("bustan")

# Common Decorators
from .addons import (
    ContextId,
    DiscoveryModule,
    DiscoveryService,
    ModuleRef,
    application_context_id,
    durable_context_id,
    request_context_id,
)

# Application Wrapper
from .app.application import Application, ApplicationContext
from .app.bootstrap import create_app, create_app_context
from .common.decorators.controller import Controller
from .common.decorators.injectable import Inject, Injectable, OptionalDep
from .common.decorators.metadata import Reflector
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
    create_param_decorator,
)
from .common.decorators.route import Delete, Get, Patch, Post, Put
from .common.types import ProviderScope as Scope
from .config import ConfigModule, ConfigService

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
from .core.ioc.scopes import DurableProvider

# Core IoC System
from .core.ioc.tokens import (
    APP_FILTER,
    APP_GUARD,
    APP_INTERCEPTOR,
    APP_PIPE,
    APPLICATION,
    INQUIRER,
    REQUEST,
    RESPONSE,
    InjectionToken,
)

# Lifecycle Protocols
from .core.lifecycle.hooks import (
    BeforeApplicationShutdown,
    OnApplicationBootstrap,
    OnApplicationShutdown,
    OnModuleDestroy,
    OnModuleInit,
)
from .core.module.builder import ConfigurableModuleBuilder

# Core Module System
from .core.module.decorators import Global, Module
from .core.module.dynamic import DynamicModule
from .core.module.graph import ModuleGraph, ModuleNode
from .logger import Logger, LoggerService, LogLevel
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

# Pipeline Components
from .pipeline import (
    ArgumentsHost,
    CallHandler,
    DefaultValuePipe,
    ExceptionFilter,
    ExecutionContext,
    Guard,
    HttpArgumentsHost,
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
from .platform.http.abstractions import (
    HttpFormData,
    HttpQueryParams,
    HttpRequest,
    HttpResponse,
    HttpUrl,
)
from .platform.http.versioning import VERSION_NEUTRAL, VersioningOptions, VersioningType
from .security import CorsOptions, SkipThrottle, ThrottlerGuard, ThrottlerModule, ThrottlerStorage

__all__ = (
    "__version__",
    "Application",
    "ApplicationContext",
    "APPLICATION",
    "APP_FILTER",
    "APP_GUARD",
    "APP_INTERCEPTOR",
    "APP_PIPE",
    "ArgumentsHost",
    "CallHandler",
    "ApiBearerAuth",
    "ApiBody",
    "ApiOperation",
    "ApiParam",
    "ApiQuery",
    "ApiResponse",
    "ApiTags",
    "BadRequestException",
    "Body",
    "BeforeApplicationShutdown",
    "Cookies",
    "create_app",
    "create_app_context",
    "create_param_decorator",
    "BustanError",
    "ContextId",
    "Controller",
    "Delete",
    "DiscoveryModule",
    "DiscoveryService",
    "DurableProvider",
    "DynamicModule",
    "DocumentBuilder",
    "ExecutionContext",
    "ExceptionFilter",
    "ExportViolationError",
    "Get",
    "Global",
    "Guard",
    "GuardRejectedError",
    "Header",
    "HostParam",
    "HttpArgumentsHost",
    "HttpFormData",
    "HttpQueryParams",
    "HttpRequest",
    "HttpResponse",
    "HttpUrl",
    "Inject",
    "Injectable",
    "INQUIRER",
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
    "ModuleRef",
    "Module",
    "ModuleGraph",
    "ModuleNode",
    "ModuleCycleError",
    "OptionalDep",
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
    "Reflector",
    "REQUEST",
    "RESPONSE",
    "RouteDefinitionError",
    "Scope",
    "DefaultValuePipe",
    "UploadedFile",
    "UploadedFiles",
    "ValidationPipe",
    "application_context_id",
    "durable_context_id",
    "Ip",
    "request_context_id",
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
