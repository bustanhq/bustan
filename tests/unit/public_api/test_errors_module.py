"""Unit tests over the supported public surface of the exception types."""

from __future__ import annotations

import bustan.errors as bustan_errors
from bustan.kernel.errors import (
    AuthenticationRequiredError,
    AuthenticatorRegistryError,
    BadGatewayException,
    BadRequestException,
    BustanError,
    ConflictException,
    ContentTooLargeException,
    CorsConfigurationError,
    ExportViolationError,
    ForbiddenException,
    GatewayTimeoutException,
    GuardRejectedError,
    HttpException,
    InternalServerErrorException,
    InvalidControllerError,
    InvalidModuleError,
    InvalidPipelineError,
    InvalidProviderError,
    LifecycleError,
    MethodNotAllowedException,
    ModuleCycleError,
    NotFoundException,
    NotImplementedException,
    ParameterBindingError,
    ProviderResolutionError,
    RouteDefinitionError,
    ServiceUnavailableException,
    TooManyRequestsException,
    UnauthorizedException,
    UnprocessableEntityException,
    UnsupportedMediaTypeException,
)
from bustan.runtime.execution import RequestTimeoutError
from bustan.runtime.params import RequestBodyTooLargeError


def test_errors_module_exposes_the_supported_exception_types() -> None:
    assert bustan_errors.__all__ == (
        "AuthenticationRequiredError",
        "AuthenticatorRegistryError",
        "BadGatewayException",
        "ConflictException",
        "ContentTooLargeException",
        "CorsConfigurationError",
        "ExportViolationError",
        "ForbiddenException",
        "GatewayTimeoutException",
        "GuardRejectedError",
        "HttpException",
        "InternalServerErrorException",
        "InvalidControllerError",
        "InvalidModuleError",
        "InvalidPipelineError",
        "InvalidProviderError",
        "LifecycleError",
        "MethodNotAllowedException",
        "ModuleCycleError",
        "NotFoundException",
        "NotImplementedException",
        "BadRequestException",
        "ParameterBindingError",
        "ProviderResolutionError",
        "RequestBodyTooLargeError",
        "RequestTimeoutError",
        "RouteDefinitionError",
        "ServiceUnavailableException",
        "TooManyRequestsException",
        "UnauthorizedException",
        "UnprocessableEntityException",
        "UnsupportedMediaTypeException",
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
    assert bustan_errors.RequestBodyTooLargeError is RequestBodyTooLargeError
    assert bustan_errors.RequestTimeoutError is RequestTimeoutError
    assert bustan_errors.RouteDefinitionError is RouteDefinitionError
    assert bustan_errors.BustanError is BustanError
    assert bustan_errors.AuthenticationRequiredError is AuthenticationRequiredError
    assert bustan_errors.AuthenticatorRegistryError is AuthenticatorRegistryError
    assert bustan_errors.BadGatewayException is BadGatewayException
    assert bustan_errors.ConflictException is ConflictException
    assert bustan_errors.ContentTooLargeException is ContentTooLargeException
    assert bustan_errors.CorsConfigurationError is CorsConfigurationError
    assert bustan_errors.ForbiddenException is ForbiddenException
    assert bustan_errors.GatewayTimeoutException is GatewayTimeoutException
    assert bustan_errors.HttpException is HttpException
    assert bustan_errors.InternalServerErrorException is InternalServerErrorException
    assert bustan_errors.MethodNotAllowedException is MethodNotAllowedException
    assert bustan_errors.NotFoundException is NotFoundException
    assert bustan_errors.NotImplementedException is NotImplementedException
    assert bustan_errors.ServiceUnavailableException is ServiceUnavailableException
    assert bustan_errors.TooManyRequestsException is TooManyRequestsException
    assert bustan_errors.UnauthorizedException is UnauthorizedException
    assert bustan_errors.UnprocessableEntityException is UnprocessableEntityException
    assert bustan_errors.UnsupportedMediaTypeException is UnsupportedMediaTypeException
