"""Bustan – A dependency injection framework for building modular Starlette applications."""

from __future__ import annotations

import importlib.metadata

# Metadata
__version__ = importlib.metadata.version("bustan")

# Common Decorators
from .common.decorators.injectable import Inject, Injectable, Optional
from .common.decorators.metadata import Reflector
from .common.decorators.controller import Controller
from .common.decorators.route import Get, Post, Put, Patch, Delete
from .common.decorators.parameter import (
    Body,
    Cookies,
    create_param_decorator,
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
from .core.module.decorators import Global, Module
from .core.module.dynamic import DynamicModule
from .core.module.builder import ConfigurableModuleBuilder
from .core.module.graph import ModuleGraph, ModuleNode

# Core IoC System
from .core.ioc.tokens import (
    APPLICATION,
    APP_FILTER,
    APP_GUARD,
    APP_INTERCEPTOR,
    APP_PIPE,
    INQUIRER,
    InjectionToken,
    REQUEST,
    RESPONSE,
)
from .core.ioc.scopes import DurableProvider

# Pipeline Components
from .pipeline import (
    ArgumentsHost,
    CallHandler,
    DefaultValuePipe,
    ExecutionContext,
    ExceptionFilter,
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

# Application Wrapper
from .app.application import Application, ApplicationContext
from .app.bootstrap import create_app, create_app_context
from .addons import (
    ContextId,
    DiscoveryModule,
    DiscoveryService,
    ModuleRef,
    application_context_id,
    durable_context_id,
    request_context_id,
)
from .platform.http.abstractions import HttpRequest, HttpResponse
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
    BeforeApplicationShutdown,
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
    "HttpRequest",
    "HttpResponse",
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
    "Optional",
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
