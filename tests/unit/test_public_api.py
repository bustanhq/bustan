"""Unit tests over the supported public surface of the root package."""

from __future__ import annotations

import importlib.metadata

import bustan
from bustan.addons import ContextId as InternalContextId
from bustan.addons import DiscoveryModule as InternalDiscoveryModule
from bustan.addons import DiscoveryService as InternalDiscoveryService
from bustan.addons import ModuleRef as InternalModuleRef
from bustan.addons import application_context_id as internal_application_context_id
from bustan.addons import durable_context_id as internal_durable_context_id
from bustan.addons import request_context_id as internal_request_context_id
from bustan.app.application import Application as InternalApplication
from bustan.app.application import ApplicationContext as InternalApplicationContext
from bustan.app.bootstrap import create_app as internal_create_app
from bustan.app.bootstrap import create_app_context as internal_create_app_context
from bustan.common.decorators.controller import Controller as InternalController
from bustan.common.decorators.injectable import Inject as InternalInject
from bustan.common.decorators.injectable import Injectable as InternalInjectable
from bustan.common.decorators.injectable import OptionalDep as InternalOptionalDep
from bustan.common.decorators.metadata import Reflector as InternalReflector
from bustan.common.decorators.parameter import Cookies as InternalCookies
from bustan.common.decorators.parameter import HostParam as InternalHostParam
from bustan.common.decorators.parameter import Ip as InternalIp
from bustan.common.decorators.parameter import UploadedFile as InternalUploadedFile
from bustan.common.decorators.parameter import UploadedFiles as InternalUploadedFiles
from bustan.common.decorators.parameter import (
    create_param_decorator as InternalCreateParamDecorator,
)
from bustan.common.decorators.route import Delete as InternalDelete
from bustan.common.decorators.route import Get as InternalGet
from bustan.common.decorators.route import Patch as InternalPatch
from bustan.common.decorators.route import Post as InternalPost
from bustan.common.decorators.route import Put as InternalPut
from bustan.common.types import ClassProvider as InternalClassProvider
from bustan.common.types import ExistingProvider as InternalExistingProvider
from bustan.common.types import FactoryProvider as InternalFactoryProvider
from bustan.common.types import ProviderScope
from bustan.common.types import ValueProvider as InternalValueProvider
from bustan.configuration import ConfigModule as InternalConfigModule
from bustan.configuration import ConfigService as InternalConfigService
from bustan.contracts import AbstractHttpAdapter as InternalAbstractHttpAdapter
from bustan.contracts import AdapterCapabilities as InternalAdapterCapabilities
from bustan.contracts import AdapterRoute as InternalAdapterRoute
from bustan.contracts import HttpFormData as InternalHttpFormData
from bustan.contracts import HttpQueryParams as InternalHttpQueryParams
from bustan.contracts import HttpRequest as InternalHttpRequest
from bustan.contracts import HttpResponse as InternalHttpResponse
from bustan.contracts import HttpUrl as InternalHttpUrl
from bustan.health import HealthIndicator as InternalHealthIndicator
from bustan.health import HealthIndicatorResult as InternalHealthIndicatorResult
from bustan.health import HealthModule as InternalHealthModule
from bustan.health import HealthReport as InternalHealthReport
from bustan.health import HealthService as InternalHealthService
from bustan.health import HealthStatus as InternalHealthStatus
from bustan.health import ReadinessState as InternalReadinessState
from bustan.kernel.errors import (
    BadRequestException,
)
from bustan.kernel.ioc.scopes import DurableProvider as InternalDurableProvider
from bustan.kernel.ioc.tokens import APP_FILTER as InternalAppFilter
from bustan.kernel.ioc.tokens import APP_GUARD as InternalAppGuard
from bustan.kernel.ioc.tokens import APP_INTERCEPTOR as InternalAppInterceptor
from bustan.kernel.ioc.tokens import APP_PIPE as InternalAppPipe
from bustan.kernel.ioc.tokens import APPLICATION as InternalApplicationToken
from bustan.kernel.ioc.tokens import INQUIRER as InternalInquirerToken
from bustan.kernel.ioc.tokens import REQUEST as InternalRequestToken
from bustan.kernel.ioc.tokens import RESPONSE as InternalResponseToken
from bustan.kernel.ioc.tokens import InjectionToken as InternalInjectionToken
from bustan.kernel.lifecycle.hooks import (
    BeforeApplicationShutdown as InternalBeforeApplicationShutdown,
)
from bustan.kernel.lifecycle.hooks import OnApplicationBootstrap as InternalOnApplicationBootstrap
from bustan.kernel.lifecycle.hooks import OnApplicationShutdown as InternalOnApplicationShutdown
from bustan.kernel.lifecycle.hooks import OnModuleDestroy as InternalOnModuleDestroy
from bustan.kernel.lifecycle.hooks import OnModuleInit as InternalOnModuleInit
from bustan.kernel.module.builder import (
    ConfigurableModuleBuilder as InternalConfigurableModuleBuilder,
)
from bustan.kernel.module.decorators import Global as InternalGlobal
from bustan.kernel.module.decorators import Module as InternalModule
from bustan.kernel.module.dynamic import DynamicModule as InternalDynamicModule
from bustan.kernel.module.graph import ModuleGraph as InternalModuleGraph
from bustan.kernel.module.graph import ModuleNode as InternalModuleNode
from bustan.observability import Logger as InternalLogger
from bustan.observability import LoggerService as InternalLoggerService
from bustan.observability import LogLevel as InternalLogLevel
from bustan.observability import MetricsSink as InternalMetricsSink
from bustan.observability import ObservabilityHooks as InternalObservabilityHooks
from bustan.observability import RequestTracer as InternalRequestTracer
from bustan.observability import SpanContext as InternalSpanContext
from bustan.observability import SpanKind as InternalSpanKind
from bustan.observability import SpanStatus as InternalSpanStatus
from bustan.observability import TraceSpan as InternalTraceSpan
from bustan.openapi import ApiBearerAuth as InternalApiBearerAuth
from bustan.openapi import ApiBody as InternalApiBody
from bustan.openapi import ApiOperation as InternalApiOperation
from bustan.openapi import ApiParam as InternalApiParam
from bustan.openapi import ApiQuery as InternalApiQuery
from bustan.openapi import ApiResponse as InternalApiResponse
from bustan.openapi import ApiTags as InternalApiTags
from bustan.openapi import DocumentBuilder as InternalDocumentBuilder
from bustan.openapi import SwaggerModule as InternalSwaggerModule
from bustan.openapi import SwaggerOptions as InternalSwaggerOptions
from bustan.pipeline import ArgumentsHost as InternalArgumentsHost
from bustan.pipeline import CallHandler as InternalCallHandler
from bustan.pipeline import DefaultValuePipe as InternalDefaultValuePipe
from bustan.pipeline import ExceptionFilter as InternalExceptionFilter
from bustan.pipeline import ExecutionContext as InternalExecutionContext
from bustan.pipeline import Guard as InternalGuard
from bustan.pipeline import HttpArgumentsHost as InternalHttpArgumentsHost
from bustan.pipeline import Interceptor as InternalInterceptor
from bustan.pipeline import ParseArrayPipe as InternalParseArrayPipe
from bustan.pipeline import ParseBoolPipe as InternalParseBoolPipe
from bustan.pipeline import ParseEnumPipe as InternalParseEnumPipe
from bustan.pipeline import ParseFloatPipe as InternalParseFloatPipe
from bustan.pipeline import ParseIntPipe as InternalParseIntPipe
from bustan.pipeline import ParseUUIDPipe as InternalParseUUIDPipe
from bustan.pipeline import Pipe as InternalPipe
from bustan.pipeline import ValidationPipe as InternalValidationPipe
from bustan.pipeline.auth import AUTHENTICATOR_REGISTRY as InternalAuthenticatorRegistry
from bustan.pipeline.auth import Authenticator as InternalAuthenticator
from bustan.pipeline.auth import Principal as InternalPrincipal
from bustan.pipeline.decorators import UseFilters as InternalUseFilters
from bustan.pipeline.decorators import UseGuards as InternalUseGuards
from bustan.pipeline.decorators import UseInterceptors as InternalUseInterceptors
from bustan.pipeline.decorators import UsePipes as InternalUsePipes
from bustan.pipeline.filters import ProblemDetails as InternalProblemDetails
from bustan.pipeline.filters import (
    ProblemDetailsExceptionFilter as InternalProblemDetailsExceptionFilter,
)
from bustan.pipeline.middleware import Middleware as InternalMiddleware
from bustan.pipeline.middleware import MiddlewareConsumer as InternalMiddlewareConsumer
from bustan.runtime.adapter import AdapterRuntime as InternalAdapterRuntime
from bustan.runtime.params import RequestLimits as InternalRequestLimits
from bustan.runtime.responses import (
    DefaultResponseSerializer as InternalDefaultResponseSerializer,
)
from bustan.runtime.responses import ResponseSerializer as InternalResponseSerializer
from bustan.runtime.versioning import VERSION_NEUTRAL as InternalVersionNeutral
from bustan.runtime.versioning import VersioningOptions as InternalVersioningOptions
from bustan.runtime.versioning import VersioningType as InternalVersioningType
from bustan.security import CorsOptions as InternalCorsOptions
from bustan.security import SkipThrottle as InternalSkipThrottle
from bustan.security import ThrottlerGuard as InternalThrottlerGuard
from bustan.security import ThrottlerModule as InternalThrottlerModule
from bustan.security import ThrottlerStorage as InternalThrottlerStorage
from bustan.security.policy import Audit as InternalAudit
from bustan.security.policy import Auth as InternalAuth
from bustan.security.policy import Cache as InternalCache
from bustan.security.policy import DeprecatedRoute as InternalDeprecatedRoute
from bustan.security.policy import Idempotent as InternalIdempotent
from bustan.security.policy import Owner as InternalOwner
from bustan.security.policy import Permissions as InternalPermissions
from bustan.security.policy import Public as InternalPublic
from bustan.security.policy import RateLimit as InternalRateLimit
from bustan.security.policy import Roles as InternalRoles
from bustan.security.throttler import ThrottleState as InternalThrottleState


def test_root_package_exposes_the_supported_public_api() -> None:
    assert bustan.__all__ == (
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
        "ClassProvider",
        "ContextId",
        "Controller",
        "DefaultResponseSerializer",
        "Delete",
        "DeprecatedRoute",
        "DiscoveryModule",
        "DiscoveryService",
        "DurableProvider",
        "DynamicModule",
        "DocumentBuilder",
        "ExecutionContext",
        "ExceptionFilter",
        "ExistingProvider",
        "ExportViolationError",
        "FactoryProvider",
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
        "ValueProvider",
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
    assert bustan.__version__ == importlib.metadata.version("bustan")
    assert bustan.Application is InternalApplication
    assert bustan.ApplicationContext is InternalApplicationContext
    assert bustan.APPLICATION is InternalApplicationToken
    assert bustan.APP_FILTER is InternalAppFilter
    assert bustan.APP_GUARD is InternalAppGuard
    assert bustan.APP_INTERCEPTOR is InternalAppInterceptor
    assert bustan.APP_PIPE is InternalAppPipe
    assert bustan.ArgumentsHost is InternalArgumentsHost
    assert bustan.CallHandler is InternalCallHandler
    assert bustan.ApiBearerAuth is InternalApiBearerAuth
    assert bustan.ApiBody is InternalApiBody
    assert bustan.ApiOperation is InternalApiOperation
    assert bustan.ApiParam is InternalApiParam
    assert bustan.ApiQuery is InternalApiQuery
    assert bustan.ApiResponse is InternalApiResponse
    assert bustan.ApiTags is InternalApiTags
    assert bustan.AbstractHttpAdapter is InternalAbstractHttpAdapter
    assert bustan.AdapterCapabilities is InternalAdapterCapabilities
    assert bustan.AdapterRoute is InternalAdapterRoute
    assert bustan.AdapterRuntime is InternalAdapterRuntime
    assert bustan.Audit is InternalAudit
    assert bustan.Auth is InternalAuth
    assert bustan.AUTHENTICATOR_REGISTRY is InternalAuthenticatorRegistry
    assert bustan.Authenticator is InternalAuthenticator
    assert bustan.Principal is InternalPrincipal
    assert bustan.Cache is InternalCache
    assert bustan.DeprecatedRoute is InternalDeprecatedRoute
    assert bustan.Idempotent is InternalIdempotent
    assert bustan.Owner is InternalOwner
    assert bustan.Permissions is InternalPermissions
    assert bustan.ProblemDetails is InternalProblemDetails
    assert bustan.ProblemDetailsExceptionFilter is InternalProblemDetailsExceptionFilter
    assert bustan.Public is InternalPublic
    assert bustan.RateLimit is InternalRateLimit
    assert bustan.ResponseSerializer is InternalResponseSerializer
    assert bustan.DefaultResponseSerializer is InternalDefaultResponseSerializer
    assert bustan.Roles is InternalRoles
    assert bustan.BadRequestException is BadRequestException
    assert bustan.BeforeApplicationShutdown is InternalBeforeApplicationShutdown
    assert bustan.Cookies is InternalCookies
    assert bustan.DefaultValuePipe is InternalDefaultValuePipe
    assert bustan.ExecutionContext is InternalExecutionContext
    assert bustan.ExceptionFilter is InternalExceptionFilter
    assert bustan.Guard is InternalGuard
    assert bustan.Global is InternalGlobal
    assert bustan.HealthIndicator is InternalHealthIndicator
    assert bustan.HealthIndicatorResult is InternalHealthIndicatorResult
    assert bustan.HealthModule is InternalHealthModule
    assert bustan.HealthReport is InternalHealthReport
    assert bustan.HealthService is InternalHealthService
    assert bustan.HealthStatus is InternalHealthStatus
    assert bustan.HostParam is InternalHostParam
    assert bustan.HttpArgumentsHost is InternalHttpArgumentsHost
    assert bustan.HttpFormData is InternalHttpFormData
    assert bustan.HttpQueryParams is InternalHttpQueryParams
    assert bustan.HttpRequest is InternalHttpRequest
    assert bustan.HttpResponse is InternalHttpResponse
    assert bustan.HttpUrl is InternalHttpUrl
    assert bustan.Inject is InternalInject
    assert bustan.Ip is InternalIp
    assert bustan.INQUIRER is InternalInquirerToken
    assert bustan.InjectionToken is InternalInjectionToken
    assert bustan.Interceptor is InternalInterceptor
    assert bustan.LogLevel is InternalLogLevel
    assert bustan.Logger is InternalLogger
    assert bustan.LoggerService is InternalLoggerService
    assert bustan.MetricsSink is InternalMetricsSink
    assert bustan.Middleware is InternalMiddleware
    assert bustan.MiddlewareConsumer is InternalMiddlewareConsumer
    assert bustan.ModuleRef is InternalModuleRef
    assert bustan.ParseArrayPipe is InternalParseArrayPipe
    assert bustan.ParseBoolPipe is InternalParseBoolPipe
    assert bustan.ParseEnumPipe is InternalParseEnumPipe
    assert bustan.ParseFloatPipe is InternalParseFloatPipe
    assert bustan.ParseIntPipe is InternalParseIntPipe
    assert bustan.ParseUUIDPipe is InternalParseUUIDPipe
    assert bustan.Pipe is InternalPipe
    assert bustan.RequestLimits is InternalRequestLimits
    assert bustan.RequestTracer is InternalRequestTracer
    assert bustan.SpanContext is InternalSpanContext
    assert bustan.SpanKind is InternalSpanKind
    assert bustan.SpanStatus is InternalSpanStatus
    assert bustan.TraceSpan is InternalTraceSpan
    assert bustan.Controller is InternalController
    assert bustan.ConfigurableModuleBuilder is InternalConfigurableModuleBuilder
    assert bustan.ConfigModule is InternalConfigModule
    assert bustan.ConfigService is InternalConfigService
    assert bustan.CorsOptions is InternalCorsOptions
    assert bustan.create_app is internal_create_app
    assert bustan.create_app_context is internal_create_app_context
    assert bustan.create_param_decorator is InternalCreateParamDecorator
    assert bustan.ContextId is InternalContextId
    assert bustan.Delete is InternalDelete
    assert bustan.DiscoveryModule is InternalDiscoveryModule
    assert bustan.DiscoveryService is InternalDiscoveryService
    assert bustan.DurableProvider is InternalDurableProvider
    assert bustan.DynamicModule is InternalDynamicModule
    assert bustan.DocumentBuilder is InternalDocumentBuilder
    assert bustan.Get is InternalGet
    assert bustan.Injectable is InternalInjectable
    assert bustan.Module is InternalModule
    assert bustan.ModuleGraph is InternalModuleGraph
    assert bustan.ModuleNode is InternalModuleNode
    assert bustan.ObservabilityHooks is InternalObservabilityHooks
    assert bustan.OptionalDep is InternalOptionalDep
    assert bustan.OnApplicationBootstrap is InternalOnApplicationBootstrap
    assert bustan.OnApplicationShutdown is InternalOnApplicationShutdown
    assert bustan.OnModuleDestroy is InternalOnModuleDestroy
    assert bustan.OnModuleInit is InternalOnModuleInit
    assert bustan.Patch is InternalPatch
    assert bustan.Post is InternalPost
    assert bustan.Put is InternalPut
    assert bustan.Scope is ProviderScope
    assert bustan.ClassProvider is InternalClassProvider
    assert bustan.FactoryProvider is InternalFactoryProvider
    assert bustan.ValueProvider is InternalValueProvider
    assert bustan.ExistingProvider is InternalExistingProvider
    assert bustan.ReadinessState is InternalReadinessState
    assert bustan.Reflector is InternalReflector
    assert bustan.REQUEST is InternalRequestToken
    assert bustan.RESPONSE is InternalResponseToken
    assert bustan.UploadedFile is InternalUploadedFile
    assert bustan.UploadedFiles is InternalUploadedFiles
    assert bustan.SkipThrottle is InternalSkipThrottle
    assert bustan.SwaggerModule is InternalSwaggerModule
    assert bustan.SwaggerOptions is InternalSwaggerOptions
    assert bustan.ThrottleState is InternalThrottleState
    assert bustan.ThrottlerGuard is InternalThrottlerGuard
    assert bustan.ThrottlerModule is InternalThrottlerModule
    assert bustan.ThrottlerStorage is InternalThrottlerStorage
    assert bustan.UseFilters is InternalUseFilters
    assert bustan.UseGuards is InternalUseGuards
    assert bustan.UseInterceptors is InternalUseInterceptors
    assert bustan.UsePipes is InternalUsePipes
    assert bustan.ValidationPipe is InternalValidationPipe
    assert bustan.application_context_id is internal_application_context_id
    assert bustan.durable_context_id is internal_durable_context_id
    assert bustan.request_context_id is internal_request_context_id
    assert bustan.VERSION_NEUTRAL is InternalVersionNeutral
    assert bustan.VersioningOptions is InternalVersioningOptions
    assert bustan.VersioningType is InternalVersioningType
