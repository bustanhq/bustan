"""Unit tests into the supported public package surface."""

from __future__ import annotations

import importlib.metadata

import bustan
import bustan.errors as bustan_errors
import bustan.testing as bustan_testing
from bustan.app.application import Application as InternalApplication
from bustan.app.application import ApplicationContext as InternalApplicationContext
from bustan.app.bootstrap import create_app as internal_create_app
from bustan.app.bootstrap import create_app_context as internal_create_app_context
from bustan.common.types import ProviderScope
from bustan.common.decorators.parameter import (
    Cookies as InternalCookies,
    HostParam as InternalHostParam,
    Ip as InternalIp,
    UploadedFile as InternalUploadedFile,
    UploadedFiles as InternalUploadedFiles,
)
from bustan.common.decorators.controller import (
    Controller as InternalController,
)
from bustan.common.decorators.route import (
    Delete as InternalDelete,
    Get as InternalGet,
    Patch as InternalPatch,
    Post as InternalPost,
    Put as InternalPut,
)
from bustan.common.decorators.injectable import Injectable as InternalInjectable
from bustan.core.module.decorators import Module as InternalModule
from bustan.pipeline.decorators import (
    UseFilters as InternalUseFilters,
    UseGuards as InternalUseGuards,
    UseInterceptors as InternalUseInterceptors,
    UsePipes as InternalUsePipes,
)
from bustan.core.errors import (
    BadRequestException,
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
    BustanError,
)
from bustan.core.module.dynamic import DynamicModule as InternalDynamicModule
from bustan.core.module.builder import ConfigurableModuleBuilder as InternalConfigurableModuleBuilder
from bustan.core.ioc.tokens import (
    APP_FILTER as InternalAppFilter,
    APP_GUARD as InternalAppGuard,
    APP_INTERCEPTOR as InternalAppInterceptor,
    APP_PIPE as InternalAppPipe,
    InjectionToken as InternalInjectionToken,
)
from bustan.core.ioc.scopes import DurableProvider as InternalDurableProvider
from bustan.core.lifecycle.hooks import (
    OnApplicationBootstrap as InternalOnApplicationBootstrap,
    OnApplicationShutdown as InternalOnApplicationShutdown,
    OnModuleDestroy as InternalOnModuleDestroy,
    OnModuleInit as InternalOnModuleInit,
)
from bustan.pipeline import ExceptionFilter as InternalExceptionFilter
from bustan.pipeline import Guard as InternalGuard
from bustan.pipeline import Interceptor as InternalInterceptor
from bustan.pipeline import DefaultValuePipe as InternalDefaultValuePipe
from bustan.pipeline import ParseArrayPipe as InternalParseArrayPipe
from bustan.pipeline import ParseBoolPipe as InternalParseBoolPipe
from bustan.pipeline import ParseEnumPipe as InternalParseEnumPipe
from bustan.pipeline import ParseFloatPipe as InternalParseFloatPipe
from bustan.pipeline import ParseIntPipe as InternalParseIntPipe
from bustan.pipeline import ParseUUIDPipe as InternalParseUUIDPipe
from bustan.pipeline import Pipe as InternalPipe
from bustan.pipeline import ValidationPipe as InternalValidationPipe
from bustan.pipeline.middleware import (
    Middleware as InternalMiddleware,
    MiddlewareConsumer as InternalMiddlewareConsumer,
)
from bustan.logger import LogLevel as InternalLogLevel
from bustan.logger import Logger as InternalLogger
from bustan.logger import LoggerService as InternalLoggerService
from bustan.config import ConfigModule as InternalConfigModule
from bustan.config import ConfigService as InternalConfigService
from bustan.security import CorsOptions as InternalCorsOptions
from bustan.security import SkipThrottle as InternalSkipThrottle
from bustan.security import ThrottlerGuard as InternalThrottlerGuard
from bustan.security import ThrottlerModule as InternalThrottlerModule
from bustan.security import ThrottlerStorage as InternalThrottlerStorage
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
from bustan.platform.http.versioning import (
    VERSION_NEUTRAL as InternalVersionNeutral,
    VersioningOptions as InternalVersioningOptions,
    VersioningType as InternalVersioningType,
)
from bustan.testing import create_test_app, create_test_module, override_provider
from bustan.testing import (
    CompiledTestingModule as InternalCompiledTestingModule,
    PipelineOverrideRegistry as InternalPipelineOverrideRegistry,
    TestingModuleBuilder as InternalTestingModuleBuilder,
    create_testing_module,
)


def test_root_package_exposes_the_supported_public_api() -> None:
    assert bustan.__all__ == (
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
    assert bustan.__version__ == importlib.metadata.version("bustan")
    assert bustan.Application is InternalApplication
    assert bustan.ApplicationContext is InternalApplicationContext
    assert bustan.APP_FILTER is InternalAppFilter
    assert bustan.APP_GUARD is InternalAppGuard
    assert bustan.APP_INTERCEPTOR is InternalAppInterceptor
    assert bustan.APP_PIPE is InternalAppPipe
    assert bustan.ApiBearerAuth is InternalApiBearerAuth
    assert bustan.ApiBody is InternalApiBody
    assert bustan.ApiOperation is InternalApiOperation
    assert bustan.ApiParam is InternalApiParam
    assert bustan.ApiQuery is InternalApiQuery
    assert bustan.ApiResponse is InternalApiResponse
    assert bustan.ApiTags is InternalApiTags
    assert bustan.BadRequestException is BadRequestException
    assert bustan.Cookies is InternalCookies
    assert bustan.DefaultValuePipe is InternalDefaultValuePipe
    assert bustan.ExceptionFilter is InternalExceptionFilter
    assert bustan.Guard is InternalGuard
    assert bustan.HostParam is InternalHostParam
    assert bustan.Ip is InternalIp
    assert bustan.InjectionToken is InternalInjectionToken
    assert bustan.Interceptor is InternalInterceptor
    assert bustan.LogLevel is InternalLogLevel
    assert bustan.Logger is InternalLogger
    assert bustan.LoggerService is InternalLoggerService
    assert bustan.Middleware is InternalMiddleware
    assert bustan.MiddlewareConsumer is InternalMiddlewareConsumer
    assert bustan.ParseArrayPipe is InternalParseArrayPipe
    assert bustan.ParseBoolPipe is InternalParseBoolPipe
    assert bustan.ParseEnumPipe is InternalParseEnumPipe
    assert bustan.ParseFloatPipe is InternalParseFloatPipe
    assert bustan.ParseIntPipe is InternalParseIntPipe
    assert bustan.ParseUUIDPipe is InternalParseUUIDPipe
    assert bustan.Pipe is InternalPipe
    assert bustan.Controller is InternalController
    assert bustan.ConfigurableModuleBuilder is InternalConfigurableModuleBuilder
    assert bustan.ConfigModule is InternalConfigModule
    assert bustan.ConfigService is InternalConfigService
    assert bustan.CorsOptions is InternalCorsOptions
    assert bustan.create_app is internal_create_app
    assert bustan.create_app_context is internal_create_app_context
    assert bustan.Delete is InternalDelete
    assert bustan.DurableProvider is InternalDurableProvider
    assert bustan.DynamicModule is InternalDynamicModule
    assert bustan.DocumentBuilder is InternalDocumentBuilder
    assert bustan.Get is InternalGet
    assert bustan.Injectable is InternalInjectable
    assert bustan.Module is InternalModule
    assert bustan.OnApplicationBootstrap is InternalOnApplicationBootstrap
    assert bustan.OnApplicationShutdown is InternalOnApplicationShutdown
    assert bustan.OnModuleDestroy is InternalOnModuleDestroy
    assert bustan.OnModuleInit is InternalOnModuleInit
    assert bustan.Patch is InternalPatch
    assert bustan.Post is InternalPost
    assert bustan.Put is InternalPut
    assert bustan.Scope is ProviderScope
    assert bustan.UploadedFile is InternalUploadedFile
    assert bustan.UploadedFiles is InternalUploadedFiles
    assert bustan.SkipThrottle is InternalSkipThrottle
    assert bustan.SwaggerModule is InternalSwaggerModule
    assert bustan.SwaggerOptions is InternalSwaggerOptions
    assert bustan.ThrottlerGuard is InternalThrottlerGuard
    assert bustan.ThrottlerModule is InternalThrottlerModule
    assert bustan.ThrottlerStorage is InternalThrottlerStorage
    assert bustan.UseFilters is InternalUseFilters
    assert bustan.UseGuards is InternalUseGuards
    assert bustan.UseInterceptors is InternalUseInterceptors
    assert bustan.UsePipes is InternalUsePipes
    assert bustan.ValidationPipe is InternalValidationPipe
    assert bustan.VERSION_NEUTRAL is InternalVersionNeutral
    assert bustan.VersioningOptions is InternalVersioningOptions
    assert bustan.VersioningType is InternalVersioningType


def test_testing_module_exposes_the_supported_helpers() -> None:
    assert bustan_testing.__all__ == (
        "CompiledTestingModule",
        "PipelineOverrideRegistry",
        "TestingModuleBuilder",
        "create_test_app",
        "create_test_module",
        "create_testing_module",
        "override_provider",
    )
    assert bustan_testing.CompiledTestingModule is InternalCompiledTestingModule
    assert bustan_testing.PipelineOverrideRegistry is InternalPipelineOverrideRegistry
    assert bustan_testing.TestingModuleBuilder is InternalTestingModuleBuilder
    assert bustan_testing.create_test_app is create_test_app
    assert bustan_testing.create_test_module is create_test_module
    assert bustan_testing.create_testing_module is create_testing_module
    assert bustan_testing.override_provider is override_provider


def test_errors_module_exposes_the_supported_exception_types() -> None:
    assert bustan_errors.__all__ == (
        "ExportViolationError",
        "GuardRejectedError",
        "InvalidControllerError",
        "InvalidModuleError",
        "InvalidPipelineError",
        "InvalidProviderError",
        "LifecycleError",
        "ModuleCycleError",
        "BadRequestException",
        "ParameterBindingError",
        "ProviderResolutionError",
        "RouteDefinitionError",
        "BustanError",
    )
    assert bustan_errors.BadRequestException is BadRequestException
    assert bustan_errors.ExportViolationError is ExportViolationError
    assert bustan_errors.GuardRejectedError is GuardRejectedError
    assert bustan_errors.InvalidControllerError is InvalidControllerError
    assert bustan_errors.InvalidModuleError is InvalidModuleError
    assert bustan_errors.InvalidPipelineError is InvalidPipelineError
    assert bustan_errors.InvalidProviderError is InvalidProviderError
    assert bustan_errors.LifecycleError is LifecycleError
    assert bustan_errors.ModuleCycleError is ModuleCycleError
    assert bustan_errors.ParameterBindingError is ParameterBindingError
    assert bustan_errors.ProviderResolutionError is ProviderResolutionError
    assert bustan_errors.RouteDefinitionError is RouteDefinitionError
    assert bustan_errors.BustanError is BustanError
