"""Public exception types for the star package."""

class StarError(Exception):
    """Base exception for the framework."""


class InvalidModuleError(StarError):
    """Raised when module declarations or imports are invalid."""


class InvalidControllerError(StarError):
    """Raised when a controller declaration is invalid."""


class InvalidProviderError(StarError):
    """Raised when a provider declaration is invalid."""


class InvalidPipelineError(StarError):
    """Raised when pipeline decorators or components are invalid."""


class LifecycleError(StarError):
    """Raised when application lifecycle hooks fail."""


class ModuleCycleError(InvalidModuleError):
    """Raised when a module import cycle is detected."""


class ExportViolationError(InvalidModuleError):
    """Raised when a module exports a provider it does not declare."""


class ProviderResolutionError(StarError):
    """Raised when dependency resolution fails."""


class RouteDefinitionError(StarError):
    """Raised when route metadata is malformed or duplicated."""


class ParameterBindingError(StarError):
    """Raised when request parameters cannot be bound."""


class GuardRejectedError(StarError):
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
    "StarError",
)