"""Unit tests that lock down the supported public package surface."""

from __future__ import annotations

import importlib.metadata

import bustan
import bustan.errors as star_errors
import bustan.testing as star_testing
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
from bustan.metadata import ClassProviderDef, ExistingProviderDef, FactoryProviderDef, ValueProviderDef
from bustan.pipeline import ExceptionFilter, Guard, Interceptor, Pipe
from bustan.testing import create_test_app, create_test_module, override_provider


def test_root_package_exposes_the_supported_public_api() -> None:
    assert bustan.__all__ == (
        "__version__",
        "ClassProviderDef",
        "ExceptionFilter",
        "ExistingProviderDef",
        "FactoryProviderDef",
        "Guard",
        "Interceptor",
        "Pipe",
        "ValueProviderDef",
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
    assert bustan.ClassProviderDef is ClassProviderDef
    assert bustan.ExceptionFilter is ExceptionFilter
    assert bustan.ExistingProviderDef is ExistingProviderDef
    assert bustan.FactoryProviderDef is FactoryProviderDef
    assert bustan.Guard is Guard
    assert bustan.Interceptor is Interceptor
    assert bustan.Pipe is Pipe
    assert bustan.ValueProviderDef is ValueProviderDef
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
        "BustanError",
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
    assert star_errors.BustanError is BustanError