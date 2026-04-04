"""Unit tests that lock down the supported public package surface."""

from __future__ import annotations

import importlib.metadata

import star
import star.errors as star_errors
import star.testing as star_testing
from star.application import bootstrap, create_app
from star.decorators import (
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
from star.errors import (
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
    StarError,
)
from star.pipeline import ExceptionFilter, Guard, Interceptor, Pipe
from star.testing import create_test_app, create_test_module, override_provider


def test_root_package_exposes_the_supported_public_api() -> None:
    assert star.__all__ == (
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
    assert star.__version__ == importlib.metadata.version("star")
    assert star.ExceptionFilter is ExceptionFilter
    assert star.Guard is Guard
    assert star.Interceptor is Interceptor
    assert star.Pipe is Pipe
    assert star.bootstrap is bootstrap
    assert star.Controller is Controller
    assert star.create_app is create_app
    assert star.Delete is Delete
    assert star.Get is Get
    assert star.Injectable is Injectable
    assert star.Module is Module
    assert star.Patch is Patch
    assert star.Post is Post
    assert star.Put is Put
    assert star.UseFilters is UseFilters
    assert star.UseGuards is UseGuards
    assert star.UseInterceptors is UseInterceptors
    assert star.UsePipes is UsePipes


def test_testing_module_exposes_the_supported_helpers() -> None:
    assert star_testing.__all__ == (
        "create_test_app",
        "create_test_module",
        "override_provider",
    )
    assert star_testing.create_test_app is create_test_app
    assert star_testing.create_test_module is create_test_module
    assert star_testing.override_provider is override_provider


def test_errors_module_exposes_the_supported_exception_types() -> None:
    assert star_errors.__all__ == (
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
        "StarError",
    )
    assert star_errors.ExportViolationError is ExportViolationError
    assert star_errors.GuardRejectedError is GuardRejectedError
    assert star_errors.InvalidControllerError is InvalidControllerError
    assert star_errors.InvalidModuleError is InvalidModuleError
    assert star_errors.InvalidPipelineError is InvalidPipelineError
    assert star_errors.InvalidProviderError is InvalidProviderError
    assert star_errors.LifecycleError is LifecycleError
    assert star_errors.ModuleCycleError is ModuleCycleError
    assert star_errors.ParameterBindingError is ParameterBindingError
    assert star_errors.ProviderResolutionError is ProviderResolutionError
    assert star_errors.RouteDefinitionError is RouteDefinitionError
    assert star_errors.StarError is StarError