"""Unit tests that lock down the supported public package surface."""

from __future__ import annotations

import importlib.metadata

import bustan
import bustan.errors as bustan_errors
import bustan.testing as bustan_testing
from bustan.application import bootstrap, create_app
from bustan.decorators import (
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
from bustan.errors import (
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
from bustan.pipeline import ExceptionFilter, Guard, Interceptor, Pipe
from bustan.testing import create_test_app, create_test_module, override_provider


def test_root_package_exposes_the_supported_public_api() -> None:
    assert bustan.__all__ == (
        "__version__",
        "Application",
        "ExceptionFilter",
        "Guard",
        "InjectionToken",
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
    assert bustan.__version__ == importlib.metadata.version("bustan")
    assert bustan.Application is bustan.application.Application
    assert bustan.ExceptionFilter is ExceptionFilter
    assert bustan.Guard is Guard
    assert bustan.InjectionToken is bustan.injection.InjectionToken
    assert bustan.Interceptor is Interceptor
    assert bustan.Pipe is Pipe
    assert bustan.bootstrap is bootstrap
    assert bustan.Controller is Controller
    assert bustan.create_app is create_app
    assert bustan.Delete is Delete
    assert bustan.Get is Get
    assert bustan.Injectable is Injectable
    assert bustan.Module is Module
    assert bustan.Patch is Patch
    assert bustan.Post is Post
    assert bustan.Put is Put
    assert bustan.UseFilters is UseFilters
    assert bustan.UseGuards is UseGuards
    assert bustan.UseInterceptors is UseInterceptors
    assert bustan.UsePipes is UsePipes


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
