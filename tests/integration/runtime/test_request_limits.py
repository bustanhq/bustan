"""Integration tests for the limits one application serves a single request under."""

from __future__ import annotations

import asyncio
import threading
import time
from typing import TYPE_CHECKING, Annotated, Any, cast

import anyio
import httpx
from anyio import to_thread

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
    from collections.abc import Callable

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


def test_a_sync_handler_past_its_deadline_is_answered_with_a_timeout_once_it_returns() -> None:
    # A thread cannot be interrupted, so the handler runs to its end. The caller is still
    # owed the timeout rather than the value that came back too late, and is answered only
    # once the handler has returned.
    finished: list[str] = []

    @Controller("/slow")
    class SlowController:
        @Get("/")
        def read(self) -> dict[str, str]:
            time.sleep(0.2)
            finished.append("handler")
            return {"status": "ok"}

    @Module(controllers=[SlowController])
    class AppModule:
        pass

    application = create_app(AppModule)
    set_request_limits(application, RequestLimits(timeout_seconds=0.05))

    with AsgiTestClient(cast(Any, application)) as client:
        response = client.get("/slow")
        finished_when_answered = list(finished)

    assert finished_when_answered == ["handler"]
    assert response.status_code == 504
    assert response.json()["title"] == "Gateway Timeout"


def test_a_sync_handler_past_its_deadline_keeps_its_thread_until_it_returns() -> None:
    # One thread is allowed. The first handler is held past its deadline; had its request
    # handed the thread back when the deadline passed, the second request's handler would
    # have started on it, instead of the second request waiting out a deadline of its own.
    release = threading.Event()
    started: list[str] = []

    @Controller("/work")
    class WorkController:
        @Get("/{name}")
        def read(self, name: str) -> dict[str, str]:
            started.append(name)
            release.wait(5)
            return {"name": name}

    @Module(controllers=[WorkController])
    class AppModule:
        pass

    application = create_app(AppModule)
    set_request_limits(application, RequestLimits(timeout_seconds=0.1, sync_handler_threads=1))
    statuses: dict[str, int] = {}

    async def send(client: httpx.AsyncClient, name: str) -> None:
        statuses[name] = (await client.get(f"/work/{name}")).status_code

    async def scenario() -> None:
        transport = httpx.ASGITransport(app=cast(Any, application))
        async with (
            httpx.AsyncClient(transport=transport, base_url="http://testserver") as client,
            anyio.create_task_group() as task_group,
        ):
            task_group.start_soon(send, client, "first")
            await _until(lambda: started == ["first"])
            await send(client, "second")
            release.set()

    anyio.run(scenario)

    assert started == ["first"]
    assert statuses == {"first": 504, "second": 504}


def test_a_request_cancelled_other_than_by_its_deadline_does_not_wait_for_its_thread() -> None:
    # A server cancels a request natively when its drain window closes, and is not kept
    # waiting for a handler nothing can interrupt: the request ends at once and the thread
    # runs on without it. Only an anyio cancellation, as the deadline is, waits.
    started = threading.Event()
    release = threading.Event()

    @Controller("/work")
    class WorkController:
        @Get("/")
        def read(self) -> dict[str, str]:
            started.set()
            release.wait(5)
            return {"status": "ok"}

    @Module(controllers=[WorkController])
    class AppModule:
        pass

    application = create_app(AppModule)

    async def scenario() -> bool:
        async with _client(application) as client:
            request = asyncio.create_task(client.get("/work"))
            await _until(started.is_set)
            request.cancel()
            done, _ = await asyncio.wait({request}, timeout=1)
            release.set()
            return request in done and request.cancelled()

    assert asyncio.run(scenario())


async def _until(condition: Callable[[], bool]) -> None:
    """Wait for *condition* to hold, failing rather than hanging when it never does."""

    with anyio.fail_after(5):
        while not condition():
            await anyio.sleep(0.005)


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


def test_two_applications_on_one_loop_share_the_thread_ceiling_the_last_to_serve_set() -> None:
    """The thread ceiling belongs to the loop, so whichever application serves last sets it.

    Six requests reach an application allowing two threads: two run and four wait. A request
    to an application allowing six raises the ceiling under the four, which start beside the
    first two. The first application's next six requests run two at a time again.
    """

    guard = threading.Lock()
    gate = [threading.Event()]
    running = 0
    peaks: list[int] = []

    @Controller("/threads")
    class NarrowController:
        @Get("/")
        def read(self) -> dict[str, str]:
            nonlocal running
            with guard:
                running += 1
                peaks.append(running)
            gate[0].wait(5)
            with guard:
                running -= 1
            return {"status": "ok"}

    @Module(controllers=[NarrowController])
    class NarrowModule:
        pass

    @Controller("/threads")
    class WideController:
        @Get("/")
        def read(self) -> dict[str, str]:
            return {"status": "ok"}

    @Module(controllers=[WideController])
    class WideModule:
        pass

    narrow = create_app(NarrowModule)
    set_request_limits(narrow, RequestLimits(sync_handler_threads=2))
    wide = create_app(WideModule)
    set_request_limits(wide, RequestLimits(sync_handler_threads=6))

    async def scenario() -> tuple[int, int]:
        limiter = to_thread.current_default_thread_limiter()
        async with (
            _client(narrow) as narrow_client,
            _client(wide) as wide_client,
            anyio.create_task_group() as task_group,
        ):
            for _ in range(6):
                task_group.start_soon(_expect_ok, narrow_client)
            await _until(lambda: running == 2 and limiter.statistics().tasks_waiting == 4)
            task_group.start_soon(_expect_ok, wide_client)
            await _until(lambda: running == 6)
            gate[0].set()
        raised = max(peaks)

        peaks.clear()
        gate[0] = threading.Event()
        async with _client(narrow) as narrow_client, anyio.create_task_group() as task_group:
            for _ in range(6):
                task_group.start_soon(_expect_ok, narrow_client)
            await _until(lambda: running == 2 and limiter.statistics().tasks_waiting == 4)
            gate[0].set()
        return raised, max(peaks)

    raised, restored = anyio.run(scenario)

    assert raised == 6
    assert restored == 2


def _client(application: object) -> httpx.AsyncClient:
    """Return a client that sends its requests straight to *application*."""

    transport = httpx.ASGITransport(app=cast(Any, application))
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")
