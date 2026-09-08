"""Public exception types for the bustan package."""

from __future__ import annotations

from collections.abc import Mapping
from typing import ClassVar


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


class HttpException(BustanError):
    """Base class for an exception that names the response its caller receives.

    Raise one of its subclasses from a handler, a pipe, an interceptor or a filter to
    answer the caller with a status the route would not otherwise return. Each subclass
    fixes the status, the problem type and the code the response carries, so the same
    condition is always reported the same way, and the message passed in is returned to
    the caller as the problem's ``detail``.

    A message given to a subclass whose status is 500 or above is not shown to the
    caller. Those statuses report a fault in the application rather than anything the
    caller can act on, and their messages routinely name internal detail, so the status
    reason is returned in place of the message and the message is kept in the log.

    ``headers`` adds response headers the status needs, such as the challenge a 401
    carries. Passing a header the subclass also sets by default replaces that default.
    """

    status_code: ClassVar[int] = 500
    problem_type: ClassVar[str] = "https://bustan.dev/problems/internal-server-error"
    code: ClassVar[str] = "internal-server-error"
    title: ClassVar[str] = "Internal Server Error"
    default_headers: ClassVar[tuple[tuple[str, str], ...]] = ()

    def __init__(
        self,
        detail: str | None = None,
        *,
        headers: Mapping[str, str] | None = None,
    ):
        super().__init__(detail if detail is not None else self.title)
        self.detail = detail if detail is not None else self.title
        self.headers: dict[str, str] = {**dict(self.default_headers), **dict(headers or {})}


class UnauthorizedException(HttpException):
    """Raise to answer 401 when the request carries no usable credentials.

    The response carries a ``WWW-Authenticate`` challenge, because a 401 without one
    tells a client it must authenticate without telling it how. The default names the
    bearer scheme; pass ``headers`` to state the scheme the application really uses.

    Use this when the caller is unknown. A caller the application has identified and is
    refusing anyway is answered with :class:`ForbiddenException`.
    """

    status_code: ClassVar[int] = 401
    problem_type: ClassVar[str] = "https://bustan.dev/problems/unauthorized"
    code: ClassVar[str] = "unauthorized"
    title: ClassVar[str] = "Unauthorized"
    default_headers: ClassVar[tuple[tuple[str, str], ...]] = (("WWW-Authenticate", "Bearer"),)


class ForbiddenException(HttpException):
    """Raise to answer 403 when an identified caller is not allowed to do this.

    Say what is refused, never why in terms of the application's own roles or
    permissions: the caller being refused is the one party those names must not reach.
    """

    status_code: ClassVar[int] = 403
    problem_type: ClassVar[str] = "https://bustan.dev/problems/forbidden"
    code: ClassVar[str] = "forbidden"
    title: ClassVar[str] = "Forbidden"


class NotFoundException(HttpException):
    """Raise to answer 404 when the addressed resource does not exist."""

    status_code: ClassVar[int] = 404
    problem_type: ClassVar[str] = "https://bustan.dev/problems/not-found"
    code: ClassVar[str] = "not-found"
    title: ClassVar[str] = "Not Found"


class MethodNotAllowedException(HttpException):
    """Raise to answer 405 when the resource exists but not for this method."""

    status_code: ClassVar[int] = 405
    problem_type: ClassVar[str] = "https://bustan.dev/problems/method-not-allowed"
    code: ClassVar[str] = "method-not-allowed"
    title: ClassVar[str] = "Method Not Allowed"


class ConflictException(HttpException):
    """Raise to answer 409 when the request contradicts the resource's current state."""

    status_code: ClassVar[int] = 409
    problem_type: ClassVar[str] = "https://bustan.dev/problems/conflict"
    code: ClassVar[str] = "conflict"
    title: ClassVar[str] = "Conflict"


class UnsupportedMediaTypeException(HttpException):
    """Raise to answer 415 when the body is in a format the handler cannot read."""

    status_code: ClassVar[int] = 415
    problem_type: ClassVar[str] = "https://bustan.dev/problems/unsupported-media-type"
    code: ClassVar[str] = "unsupported-media-type"
    title: ClassVar[str] = "Unsupported Media Type"


class UnprocessableEntityException(HttpException):
    """Raise to answer 422 when a well-formed body asks for something impossible.

    A body the framework could not read at all is a 400 the caller is told about
    through :class:`BadRequestException`; this status is for one that parsed and then
    failed a rule the application enforces.
    """

    status_code: ClassVar[int] = 422
    problem_type: ClassVar[str] = "https://bustan.dev/problems/unprocessable-entity"
    code: ClassVar[str] = "unprocessable-entity"
    title: ClassVar[str] = "Unprocessable Content"


class TooManyRequestsException(HttpException):
    """Raise to answer 429 when the caller has exceeded a rate it is held to."""

    status_code: ClassVar[int] = 429
    problem_type: ClassVar[str] = "https://bustan.dev/problems/too-many-requests"
    code: ClassVar[str] = "too-many-requests"
    title: ClassVar[str] = "Too Many Requests"


class InternalServerErrorException(HttpException):
    """Raise to answer 500 when the application cannot serve the request.

    The message reaches the log and not the caller, so write it for whoever is on call.
    """

    status_code: ClassVar[int] = 500
    problem_type: ClassVar[str] = "https://bustan.dev/problems/internal-server-error"
    code: ClassVar[str] = "internal-server-error"
    title: ClassVar[str] = "Internal Server Error"


class NotImplementedException(HttpException):
    """Raise to answer 501 when the route exists but the behaviour is not written yet."""

    status_code: ClassVar[int] = 501
    problem_type: ClassVar[str] = "https://bustan.dev/problems/not-implemented"
    code: ClassVar[str] = "not-implemented"
    title: ClassVar[str] = "Not Implemented"


class BadGatewayException(HttpException):
    """Raise to answer 502 when a service this one depends on answered unusably."""

    status_code: ClassVar[int] = 502
    problem_type: ClassVar[str] = "https://bustan.dev/problems/bad-gateway"
    code: ClassVar[str] = "bad-gateway"
    title: ClassVar[str] = "Bad Gateway"


class ServiceUnavailableException(HttpException):
    """Raise to answer 503 when the application is up but cannot serve requests now."""

    status_code: ClassVar[int] = 503
    problem_type: ClassVar[str] = "https://bustan.dev/problems/service-unavailable"
    code: ClassVar[str] = "service-unavailable"
    title: ClassVar[str] = "Service Unavailable"


class GatewayTimeoutException(HttpException):
    """Raise to answer 504 when a service this one depends on did not answer in time."""

    status_code: ClassVar[int] = 504
    problem_type: ClassVar[str] = "https://bustan.dev/problems/gateway-timeout"
    code: ClassVar[str] = "gateway-timeout"
    title: ClassVar[str] = "Gateway Timeout"


class BadRequestException(HttpException):
    """Raised when a request fails explicit validation.

    The message reaches the caller, because it is about the request that was just
    sent: which field was wrong, where it was read from and what was expected there.
    """

    status_code: ClassVar[int] = 400
    problem_type: ClassVar[str] = "https://bustan.dev/problems/bad-request"
    code: ClassVar[str] = "bad-request"
    title: ClassVar[str] = "Bad Request"

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


class AuthenticationRequiredError(GuardRejectedError):
    """Raised when a route needs an authenticated caller and the request has none.

    It refuses exactly the requests a guard already refused; it says only that the
    refusal was for want of an identity rather than for want of a permission, which is
    what separates a 401 the caller can retry after authenticating from a 403 it cannot.
    """


class AuthenticatorRegistryError(BustanError):
    """Raised when the authenticator wiring a route needs is missing or unusable.

    A route that authenticates its callers reads its authenticators out of a registry
    bound under ``AUTHENTICATOR_REGISTRY``. A registry no module visible to the route
    provides, or one that cannot be built without awaiting it, cannot authenticate
    anybody, so every caller of that route would be refused however good its
    credentials. That is a mistake in the application rather than in the request, so it
    is raised while the application is being built, and separately from the errors that
    report a refused caller.
    """


__all__ = (
    "AuthenticationRequiredError",
    "AuthenticatorRegistryError",
    "BadGatewayException",
    "ConflictException",
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
    "RouteDefinitionError",
    "ServiceUnavailableException",
    "TooManyRequestsException",
    "UnauthorizedException",
    "UnprocessableEntityException",
    "UnsupportedMediaTypeException",
    "BustanError",
)
