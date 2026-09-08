"""Integration tests for configuring request limits the way an application must.

Every name this file takes from the framework comes from ``bustan``, ``bustan.errors``
or ``bustan.testing``, which is the whole point of it: the tests beside it reach into
the runtime package to set the limits and to name the exceptions they raise, and an
application cannot, because that package carries no compatibility commitment. What is
asserted here is therefore not only that the limits work but that they are reachable at
all from the surface an application is allowed to import.
"""

from __future__ import annotations

from typing import Any, cast

import anyio

from bustan import (
    Controller,
    ExceptionFilter,
    ExecutionContext,
    Get,
    HttpResponse,
    Module,
    Post,
    RequestLimits,
    UseFilters,
    create_app,
)
from bustan.errors import RequestBodyTooLargeError, RequestTimeoutError
from bustan.testing import AsgiTestClient

# Comfortably inside the default body limit and far outside the one configured below,
# so the same request separates a configured application from an unconfigured one.
_BODY_BYTES = 4096
_CONFIGURED_MAX_BODY_BYTES = 1024


def _notes_module() -> type[object]:
    """Return a module with one route that accepts a JSON body."""

    @Controller("/notes")
    class NotesController:
        @Post("/")
        def create(self, title: str) -> dict[str, str]:
            return {"title": title}

    @Module(controllers=[NotesController])
    class AppModule:
        pass

    return AppModule


def _oversized_note() -> tuple[bytes, dict[str, str]]:
    """Return a body the default limit accepts and the headers that declare it."""

    body = b'{"title": "' + b"a" * (_BODY_BYTES - 13) + b'"}'
    assert len(body) == _BODY_BYTES
    return body, {"content-type": "application/json", "content-length": str(len(body))}


def test_limits_given_to_create_app_refuse_what_the_default_would_have_served() -> None:
    body, headers = _oversized_note()

    with AsgiTestClient(cast(Any, create_app(_notes_module()))) as client:
        served = client.post("/notes", content=body, headers=headers)

    configured = create_app(
        _notes_module(),
        request_limits=RequestLimits(max_body_bytes=_CONFIGURED_MAX_BODY_BYTES),
    )
    with AsgiTestClient(cast(Any, configured)) as client:
        refused = client.post("/notes", content=body, headers=headers)

    assert served.status_code == 200
    assert refused.status_code == 413
    assert refused.headers["content-type"].startswith("application/problem+json")
    assert refused.json() == {
        "type": "about:blank",
        "title": "Content Too Large",
        "status": 413,
        "detail": (
            f"The request body declares {_BODY_BYTES} bytes, "
            f"over the {_CONFIGURED_MAX_BODY_BYTES} byte limit"
        ),
        "instance": "/notes",
    }


def test_two_applications_in_one_process_serve_under_their_own_limits() -> None:
    """The limits belong to an application, not to the process it happens to share."""

    body, headers = _oversized_note()

    strict = create_app(
        _notes_module(),
        request_limits=RequestLimits(max_body_bytes=_CONFIGURED_MAX_BODY_BYTES),
    )
    generous = create_app(_notes_module(), request_limits=RequestLimits(max_body_bytes=None))

    with (
        AsgiTestClient(cast(Any, strict)) as strict_client,
        AsgiTestClient(cast(Any, generous)) as generous_client,
    ):
        refused = strict_client.post("/notes", content=body, headers=headers)
        served = generous_client.post("/notes", content=body, headers=headers)
        # Read the strict application a second time while both are alive, because a
        # limit that had been process-wide would have been overwritten by the assembly
        # of the second application rather than kept by the first.
        refused_again = strict_client.post("/notes", content=body, headers=headers)

    assert refused.status_code == 413
    assert refused_again.status_code == 413
    assert served.status_code == 200


def test_the_error_a_body_limit_raises_is_catchable_from_the_supported_surface() -> None:
    seen: list[Exception] = []

    class BodyLimitFilter(ExceptionFilter):
        exception_types = (RequestBodyTooLargeError,)

        async def catch(self, exc: Exception, context: ExecutionContext) -> HttpResponse:
            seen.append(exc)
            return HttpResponse.json({"detail": "that note is too long"}, status_code=422)

    @Controller("/notes")
    class NotesController:
        @UseFilters(BodyLimitFilter())
        @Post("/")
        def create(self, title: str) -> dict[str, str]:
            return {"title": title}

    @Module(controllers=[NotesController])
    class AppModule:
        pass

    application = create_app(
        AppModule, request_limits=RequestLimits(max_body_bytes=_CONFIGURED_MAX_BODY_BYTES)
    )
    body, headers = _oversized_note()
    with AsgiTestClient(cast(Any, application)) as client:
        response = client.post("/notes", content=body, headers=headers)

    assert [type(error) for error in seen] == [RequestBodyTooLargeError]
    assert response.status_code == 422
    assert response.json() == {"detail": "that note is too long"}


def test_the_error_a_timeout_raises_is_catchable_from_the_supported_surface() -> None:
    # The case the export exists for: an application that answers a timeout with its
    # own status rather than the 504 the framework would have returned.
    seen: list[Exception] = []

    class TimeoutFilter(ExceptionFilter):
        exception_types = (RequestTimeoutError,)

        async def catch(self, exc: Exception, context: ExecutionContext) -> HttpResponse:
            seen.append(exc)
            return HttpResponse.json({"detail": "the shop is busy"}, status_code=503)

    @Controller("/slow")
    class SlowController:
        @UseFilters(TimeoutFilter())
        @Get("/")
        async def read(self) -> dict[str, str]:
            await anyio.sleep(5)
            return {"status": "ok"}

    @Module(controllers=[SlowController])
    class AppModule:
        pass

    application = create_app(AppModule, request_limits=RequestLimits(timeout_seconds=0.05))
    with AsgiTestClient(cast(Any, application)) as client:
        response = client.get("/slow")

    assert [type(error) for error in seen] == [RequestTimeoutError]
    assert response.status_code == 503
    assert response.json() == {"detail": "the shop is busy"}
