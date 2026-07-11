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

    def __init__(
        self,
        message: str,
        *,
        field: str | None = None,
        source: str | None = None,
        reason: str | None = None,
    ):
        super().__init__(message)
        self.field = field
        self.source = source
        self.reason = reason

    def to_payload(self) -> dict[str, str]:
        payload = {"detail": str(self)}
        if self.field is not None:
            payload["field"] = self.field
        if self.source is not None:
            payload["source"] = self.source
        if self.reason is not None:
            payload["reason"] = self.reason
        return payload


class BadRequestException(BustanError):
    """Raised when a request fails explicit validation."""

    def __init__(
        self,
        message: str,
        *,
        field: str | None = None,
        source: str | None = None,
        reason: str | None = None,
    ):
        super().__init__(message)
        self.field = field
        self.source = source
        self.reason = reason

    def to_payload(self) -> dict[str, str]:
        payload = {"detail": str(self)}
        if self.field is not None:
            payload["field"] = self.field
        if self.source is not None:
            payload["source"] = self.source
        if self.reason is not None:
            payload["reason"] = self.reason
        return payload


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
    "BadRequestException",
    "ParameterBindingError",
    "ProviderResolutionError",
    "RouteDefinitionError",
    "BustanError",
)
