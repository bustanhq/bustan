"""Exception filter base class and resolution helpers."""

from __future__ import annotations

import inspect
import logging
from collections.abc import Awaitable
from dataclasses import asdict, dataclass
from typing import cast

from ..contracts import HttpResponse
from ..kernel.errors import BadRequestException, GuardRejectedError, ParameterBindingError
from .context import ExecutionContext

_LOGGER = logging.getLogger(__name__)
_INTERNAL_SERVER_ERROR_DETAIL = "Internal server error"

# The exceptions whose message is written for the caller rather than about the
# application: a failed validation names the caller's own field, where it was read from
# and what was expected there, and none of it is true of anything but the request that
# was just sent. Every other message is written for whoever operates the application and
# is replaced by a fixed reason before it leaves the process, so a type added later is
# masked until it is listed here deliberately.
_CALLER_FACING_EXCEPTIONS: tuple[type[Exception], ...] = (
    BadRequestException,
    ParameterBindingError,
)


@dataclass(frozen=True, slots=True)
class ProblemDetails:
    """RFC 7807 problem details payload."""

    type: str
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None
    code: str | None = None
    errors: list[dict[str, object]] | None = None


class ExceptionFilter:
    """Base class for mapping exceptions to handler results.

    Override exception_types to declare which exception classes this filter can
    handle.
    """

    exception_types: tuple[type[BaseException], ...] = (Exception,)

    def catch(self, exc: Exception, context: ExecutionContext) -> object | Awaitable[object]:
        """Convert an exception into a handler result or response payload."""

        raise exc


class ProblemDetailsExceptionFilter(ExceptionFilter):
    """Framework fallback filter that always emits problem-details responses."""

    exception_types = (Exception,)

    async def catch(self, exc: Exception, context: ExecutionContext) -> HttpResponse:
        problem = _build_problem_details(exc, context)
        if cast(int, problem["status"]) >= 500:
            _LOGGER.exception("Unhandled exception during request processing", exc_info=exc)
        response = HttpResponse.json(problem, status_code=cast(int, problem["status"]))
        response.media_type = "application/problem+json"
        return response


async def handle_exception(
    context: ExecutionContext,
    exc: Exception,
    filters: tuple[ExceptionFilter, ...],
) -> object:
    """Return the first handled result for the supplied exception."""

    current_exception = exc
    reentered = False

    while True:
        restart = False
        for exception_filter in _matching_filters(current_exception, filters):
            try:
                result = exception_filter.catch(current_exception, context)
                if inspect.isawaitable(result):
                    result = await result
            except Exception as new_exception:
                if reentered:
                    current_exception = new_exception
                    return await ProblemDetailsExceptionFilter().catch(current_exception, context)
                current_exception = new_exception
                reentered = True
                restart = True
                break

            if result is not None:
                return result

        if not restart:
            return await ProblemDetailsExceptionFilter().catch(current_exception, context)


def _matching_filters(
    exc: Exception,
    filters: tuple[ExceptionFilter, ...],
) -> tuple[ExceptionFilter, ...]:
    ranked_matches: list[tuple[bool, int, int, ExceptionFilter]] = []

    for index, exception_filter in enumerate(filters):
        match = _filter_match(exception_filter, exc)
        if match is None:
            continue

        catch_all, distance = match
        ranked_matches.append((catch_all, distance, -index, exception_filter))

    ranked_matches.sort(key=lambda item: (item[0], item[1], item[2]))
    return tuple(exception_filter for *_meta, exception_filter in ranked_matches)


def _filter_match(
    exception_filter: ExceptionFilter,
    exc: Exception,
) -> tuple[bool, int] | None:
    declared_types = exception_filter.exception_types or (Exception,)
    matching_distances = [
        _exception_distance(type(exc), declared_type)
        for declared_type in declared_types
        if isinstance(exc, declared_type)
    ]
    if not matching_distances:
        return None

    catch_all = all(declared_type in {BaseException, Exception} for declared_type in declared_types)
    return catch_all, min(matching_distances)


def _exception_distance(
    exception_type: type[BaseException], declared_type: type[BaseException]
) -> int:
    try:
        return exception_type.__mro__.index(declared_type)
    except ValueError:
        return len(exception_type.__mro__)


def _build_problem_details(exc: Exception, context: ExecutionContext) -> dict[str, object]:
    status_code, title = _problem_status(exc, context)
    request = context.request
    payload = asdict(
        ProblemDetails(
            type="about:blank",
            title=title,
            status=status_code,
            detail=_client_visible_detail(exc, status_code, title),
            instance=request.path if request is not None else None,
            errors=_problem_errors(exc),
        )
    )
    filtered_payload = {key: value for key, value in payload.items() if value is not None}

    if isinstance(exc, (BadRequestException, ParameterBindingError)):
        for key in ("field", "source", "reason"):
            value = getattr(exc, key, None)
            if value is not None:
                filtered_payload[key] = value

    return filtered_payload


def _client_visible_detail(exc: Exception, status_code: int, title: str) -> str:
    """Return the detail the caller may be shown for this exception.

    An exception message is written for whoever operates the application, so it names
    internal things freely: the dotted path of the guard that refused the request, the
    identifier of the authentication strategy the route expects, the roles the caller
    does not hold. A caller learns the application's module layout and authorization
    vocabulary from any of them and learns nothing it can act on, so only a message
    written about the caller's own request is passed through; the rest are answered with
    the status's own reason and kept where they were raised, in the log.
    """

    if status_code >= 500:
        return _INTERNAL_SERVER_ERROR_DETAIL
    if isinstance(exc, _CALLER_FACING_EXCEPTIONS):
        return str(exc) or title
    return title


def _problem_status(exc: Exception, context: ExecutionContext) -> tuple[int, str]:
    request = context.request
    if isinstance(exc, (BadRequestException, ParameterBindingError)):
        return 400, "Bad Request"
    if isinstance(exc, GuardRejectedError):
        rate_limit = request.slots.rate_limit if request is not None else None
        if rate_limit is not None and rate_limit.exceeded:
            return 429, "Too Many Requests"
        return 403, "Forbidden"
    return 500, "Internal Server Error"


def _problem_errors(exc: Exception) -> list[dict[str, object]] | None:
    if isinstance(exc, (BadRequestException, ParameterBindingError)):
        error = {
            key: value
            for key, value in {
                "field": getattr(exc, "field", None),
                "source": getattr(exc, "source", None),
                "reason": getattr(exc, "reason", None),
            }.items()
            if value is not None
        }
        if error:
            return [error]
    return None
