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
from .configuration import ConfigModule, ConfigService

# Transport Adapter Port
from .contracts import (
    AbstractHttpAdapter,
    AdapterCapabilities,
    AdapterRoute,
    HttpFormData,
    HttpQueryParams,
    HttpRequest,
    HttpResponse,
    HttpUrl,
)

# Health Probes
from .health import (
    HealthIndicator,
    HealthIndicatorResult,
    HealthModule,
    HealthReport,
    HealthService,
    HealthStatus,
    ReadinessState,
)

# Core Errors
from .kernel.errors import (
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
from .kernel.ioc.scopes import DurableProvider

# Core IoC System
from .kernel.ioc.tokens import (
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
from .kernel.lifecycle.hooks import (
    BeforeApplicationShutdown,
    OnApplicationBootstrap,
    OnApplicationShutdown,
    OnModuleDestroy,
    OnModuleInit,
)
from .kernel.module.builder import ConfigurableModuleBuilder

# Core Module System
from .kernel.module.decorators import Global, Module
from .kernel.module.dynamic import DynamicModule
from .kernel.module.graph import ModuleGraph, ModuleNode
from .observability import (
    Logger,
    LoggerService,
    LogLevel,
    MetricsSink,
    ObservabilityHooks,
    RequestTracer,
    SpanContext,
    SpanKind,
    SpanStatus,
    TraceSpan,
)
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

# Authentication Contracts
from .pipeline.auth import AUTHENTICATOR_REGISTRY, Authenticator, Principal
from .pipeline.decorators import UseFilters, UseGuards, UseInterceptors, UsePipes
from .pipeline.filters import ProblemDetails, ProblemDetailsExceptionFilter
from .pipeline.middleware import Middleware, MiddlewareConsumer
from .runtime.adapter import AdapterRuntime
from .runtime.params import RequestLimits
from .runtime.responses import ResponseSerializer
from .runtime.versioning import VERSION_NEUTRAL, VersioningOptions, VersioningType
from .security import CorsOptions, SkipThrottle, ThrottlerGuard, ThrottlerModule, ThrottlerStorage

# Route Policy Decorators
from .security.policy import (
    Audit,
    Auth,
    Cache,
    DeprecatedRoute,
    Idempotent,
    Owner,
    Permissions,
    Public,
    RateLimit,
    Roles,
)
from .security.throttler import ThrottleState

__all__ = (
    "__version__",
    "AbstractHttpAdapter",
    "AdapterCapabilities",
    "AdapterRoute",
    "AdapterRuntime",
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
    "Audit",
    "Auth",
    "AUTHENTICATOR_REGISTRY",
    "Authenticator",
    "BadRequestException",
    "Body",
    "BeforeApplicationShutdown",
    "Cookies",
    "create_app",
    "create_app_context",
    "create_param_decorator",
    "BustanError",
    "Cache",
    "ContextId",
    "Controller",
    "Delete",
    "DeprecatedRoute",
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
    "HealthIndicator",
    "HealthIndicatorResult",
    "HealthModule",
    "HealthReport",
    "HealthService",
    "HealthStatus",
    "HostParam",
    "HttpArgumentsHost",
    "HttpFormData",
    "HttpQueryParams",
    "HttpRequest",
    "HttpResponse",
    "HttpUrl",
    "Idempotent",
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
    "MetricsSink",
    "Middleware",
    "MiddlewareConsumer",
    "ModuleRef",
    "Module",
    "ModuleGraph",
    "ModuleNode",
    "ModuleCycleError",
    "ObservabilityHooks",
    "OptionalDep",
    "OnApplicationBootstrap",
    "OnApplicationShutdown",
    "OnModuleDestroy",
    "OnModuleInit",
    "Owner",
    "Param",
    "ParameterBindingError",
    "ParseArrayPipe",
    "ParseBoolPipe",
    "ParseEnumPipe",
    "ParseFloatPipe",
    "ParseIntPipe",
    "ParseUUIDPipe",
    "Patch",
    "Permissions",
    "Pipe",
    "Post",
    "Principal",
    "ProblemDetails",
    "ProblemDetailsExceptionFilter",
    "ProviderResolutionError",
    "Public",
    "Put",
    "Query",
    "RateLimit",
    "ReadinessState",
    "Reflector",
    "REQUEST",
    "RESPONSE",
    "RequestLimits",
    "RequestTracer",
    "ResponseSerializer",
    "Roles",
    "RouteDefinitionError",
    "Scope",
    "SpanContext",
    "SpanKind",
    "SpanStatus",
    "TraceSpan",
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
    "ThrottleState",
    "ThrottlerGuard",
    "ThrottlerModule",
    "ThrottlerStorage",
    "UseFilters",
    "UseGuards",
    "UseInterceptors",
    "UsePipes",
)
