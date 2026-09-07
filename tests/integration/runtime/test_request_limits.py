"""Integration tests for the limits one application serves a single request under."""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Annotated, Any, cast

import anyio
import httpx

from bustan import (
    Controller,
    ExceptionFilter,
    ExecutionContext,
    Get,
    Module,
    Post,
    UploadedFiles,
    UseFilters,
    create_app,
)
from bustan.runtime.execution import RequestTimeoutError, set_request_limits
from bustan.runtime.params import RequestLimits
from bustan.testing import AsgiTestClient

if TYPE_CHECKING:
    from bustan.app.application import Application

_URL_ENCODED = "application/x-www-form-urlencoded"


def test_a_body_over_the_declared_limit_is_refused_without_being_read() -> None:
    # The request announces ten megabytes and carries two bytes. Only the declared
    # length can produce the refusal: had the body been read to be measured, the two
    # bytes that arrived are inside the limit and the request would have been served.
    # The handler never running says the same thing from the other end.
    served: list[str] = []

    @Controller("/notes")
    class NotesController:
        @Post("/")
        def create(self, title: str) -> dict[str, str]:
            served.append(title)
            return {"title": title}

    @Module(controllers=[NotesController])
    class AppModule:
        pass

    application = create_app(AppModule)
    set_request_limits(application, RequestLimits(max_body_bytes=1024))

    with AsgiTestClient(cast(Any, application)) as client:
        response = client.post(
            "/notes",
            content=b"{}",
            headers={"content-type": "application/json", "content-length": "10485760"},
        )

    assert response.status_code == 413
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json() == {
        "type": "about:blank",
        "title": "Content Too Large",
        "status": 413,
        "detail": "The request body declares 10485760 bytes, over the 1024 byte limit",
        "instance": "/notes",
    }
    assert served == []


def test_a_body_within_the_limit_is_served_as_before() -> None:
    @Controller("/notes")
    class NotesController:
        @Post("/")
        def create(self, title: str) -> dict[str, str]:
            return {"title": title}

    @Module(controllers=[NotesController])
    class AppModule:
        pass

    application = create_app(AppModule)
    set_request_limits(application, RequestLimits(max_body_bytes=1024))

    with AsgiTestClient(cast(Any, application)) as client:
        response = client.post("/notes", json={"title": "ada"})

    assert response.status_code == 200
    assert response.json() == {"title": "ada"}


def test_more_uploaded_files_than_the_limit_allows_are_refused_with_413() -> None:
    @Controller("/uploads")
    class UploadsController:
        @Post("/")
        def upload(
            self,
            attachments: Annotated[list[object], UploadedFiles("attachments")],
        ) -> dict[str, int]:
            return {"count": len(attachments)}

    @Module(controllers=[UploadsController])
    class AppModule:
        pass

    application = create_app(AppModule)
    set_request_limits(application, RequestLimits(max_upload_files=2))

    with AsgiTestClient(cast(Any, application)) as client:
        within = client.post(
            "/uploads",
            content=b"attachments=one&attachments=two",
            headers={"content-type": _URL_ENCODED},
        )
        beyond = client.post(
            "/uploads",
            content=b"attachments=one&attachments=two&attachments=three",
            headers={"content-type": _URL_ENCODED},
        )

    assert within.status_code == 200
    assert within.json() == {"count": 2}
    assert beyond.status_code == 413
    assert beyond.json()["detail"] == (
        "The request uploads 3 files for 'attachments', over the 2 file limit"
    )


def test_a_timeout_is_answered_by_a_filter_the_application_installed() -> None:
    # The refusal travels the same path a constructor failure does, so a route that
    # declares its own filter renders its own timeout and the framework renders none.
    seen: list[Exception] = []

    class TimeoutFilter(ExceptionFilter):
        exception_types = (RequestTimeoutError,)

        async def catch(self, exc: Exception, context: ExecutionContext) -> object:
            seen.append(exc)
            return {"detail": "the shop is busy, try again"}

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

    application = create_app(AppModule)
    set_request_limits(application, RequestLimits(timeout_seconds=0.05))

    with AsgiTestClient(cast(Any, application)) as client:
        response = client.get("/slow")

    assert [type(error) for error in seen] == [RequestTimeoutError]
    assert response.status_code == 200
    assert response.json() == {"detail": "the shop is busy, try again"}


def test_a_timeout_no_application_filter_answered_is_a_504_problem_document() -> None:
    @Controller("/slow")
    class SlowController:
        @Get("/")
        async def read(self) -> dict[str, str]:
            await anyio.sleep(5)
            return {"status": "ok"}

    @Module(controllers=[SlowController])
    class AppModule:
        pass

    application = create_app(AppModule)
    set_request_limits(application, RequestLimits(timeout_seconds=0.05))

    with AsgiTestClient(cast(Any, application)) as client:
        response = client.get("/slow")

    assert response.status_code == 504
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json() == {
        "type": "about:blank",
        "title": "Gateway Timeout",
        "status": 504,
        "detail": "Gateway Timeout",
        "instance": "/slow",
    }


def test_a_request_inside_the_time_it_is_given_is_served() -> None:
    @Controller("/quick")
    class QuickController:
        @Get("/")
        async def read(self) -> dict[str, str]:
            await anyio.sleep(0)
            return {"status": "ok"}

    @Module(controllers=[QuickController])
    class AppModule:
        pass

    application = create_app(AppModule)
    set_request_limits(application, RequestLimits(timeout_seconds=5.0))

    with AsgiTestClient(cast(Any, application)) as client:
        response = client.get("/quick")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_the_configured_thread_limit_bounds_how_many_sync_handlers_run_at_once() -> None:
    # Six requests are sent at once at each setting. The measurement is taken inside the
    # handler, on the thread it is running on, so what it reports is how many handlers
    # anyio actually let run together rather than what the limiter was asked for.
    assert _peak_concurrent_sync_handlers(sync_handler_threads=2, requests=6) == 2
    assert _peak_concurrent_sync_handlers(sync_handler_threads=6, requests=6) == 6


def _peak_concurrent_sync_handlers(*, sync_handler_threads: int, requests: int) -> int:
    """Serve *requests* at once and report how many handlers ever ran together."""

    guard = threading.Lock()
    running = 0
    peak = 0

    @Controller("/threads")
    class ThreadsController:
        @Get("/")
        def read(self) -> dict[str, str]:
            nonlocal running, peak
            with guard:
                running += 1
                peak = max(peak, running)
            # Long enough that every request that is allowed to start has started
            # before the first one finishes and hands its slot on.
            time.sleep(0.05)
            with guard:
                running -= 1
            return {"status": "ok"}

    @Module(controllers=[ThreadsController])
    class AppModule:
        pass

    application = create_app(AppModule)
    set_request_limits(application, RequestLimits(sync_handler_threads=sync_handler_threads))
    anyio.run(_send_concurrently, application, requests)
    return peak


async def _send_concurrently(application: Application, requests: int) -> None:
    """Send *requests* GETs to ``/threads`` at the same time and wait for them all."""

    transport = httpx.ASGITransport(app=cast(Any, application))
    async with (
        httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
            follow_redirects=True,
        ) as client,
        anyio.create_task_group() as task_group,
    ):
        for _ in range(requests):
            task_group.start_soon(_expect_ok, client)


async def _expect_ok(client: httpx.AsyncClient) -> None:
    response = await client.get("/threads")
    assert response.status_code == 200
