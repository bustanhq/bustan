"""Public exception types for the bustan package."""

class BustanError(Exception):
    """Base exception for the framework."""


class InvalidModuleError(BustanError):
    """Raised when module declarations or imports are invalid."""


class InvalidControllerError(BustanError):
    """Raised when a controller declaration is invalid."""


class InvalidProviderError(BustanError):
    """Raised when a provider declaration is invalid."""


class InvalidPipelineError(BustanError):
    """Raised when pipeline decorators or components are invalid."""


class LifecycleError(BustanError):
    """Raised when application lifecycle hooks fail."""


class ModuleCycleError(InvalidModuleError):
    """Raised when a module import cycle is detected."""


class ExportViolationError(InvalidModuleError):
    """Raised when a module exports a provider it does not declare."""


class ProviderResolutionError(BustanError):
    """Raised when dependency resolution fails."""


class RouteDefinitionError(BustanError):
    """Raised when route metadata is malformed or duplicated."""


class ParameterBindingError(BustanError):
    """Raised when request parameters cannot be bound."""


class GuardRejectedError(BustanError):
    """Raised when a guard blocks request execution."""


__all__ = (
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