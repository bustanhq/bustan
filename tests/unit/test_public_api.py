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
from bustan.core.ioc.tokens import InjectionToken as InternalInjectionToken
from bustan.pipeline import ExceptionFilter as InternalExceptionFilter
from bustan.pipeline import Guard as InternalGuard
from bustan.pipeline import Interceptor as InternalInterceptor
from bustan.pipeline import Pipe as InternalPipe
from bustan.testing import create_test_app, create_test_module, override_provider


def test_root_package_exposes_the_supported_public_api() -> None:
    assert bustan.__all__ == (
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
    assert bustan.__version__ == importlib.metadata.version("bustan")
    assert bustan.Application is InternalApplication
    assert bustan.ApplicationContext is InternalApplicationContext
    assert bustan.ExceptionFilter is InternalExceptionFilter
    assert bustan.Guard is InternalGuard
    assert bustan.InjectionToken is InternalInjectionToken
    assert bustan.Interceptor is InternalInterceptor
    assert bustan.Pipe is InternalPipe
    assert bustan.Controller is InternalController
    assert bustan.create_app is internal_create_app
    assert bustan.create_app_context is internal_create_app_context
    assert bustan.Delete is InternalDelete
    assert bustan.DynamicModule is InternalDynamicModule
    assert bustan.Get is InternalGet
    assert bustan.Injectable is InternalInjectable
    assert bustan.Module is InternalModule
    assert bustan.Patch is InternalPatch
    assert bustan.Post is InternalPost
    assert bustan.Put is InternalPut
    assert bustan.UseFilters is InternalUseFilters
    assert bustan.UseGuards is InternalUseGuards
    assert bustan.UseInterceptors is InternalUseInterceptors
    assert bustan.UsePipes is InternalUsePipes


def test_testing_module_exposes_the_supported_helpers() -> None:
    assert bustan_testing.__all__ == (
        "create_test_app",
        "create_test_module",
        "override_provider",
    )
    assert bustan_testing.create_test_app is create_test_app
    assert bustan_testing.create_test_module is create_test_module
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
        "ParameterBindingError",
        "ProviderResolutionError",
        "RouteDefinitionError",
        "BustanError",
    )
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
