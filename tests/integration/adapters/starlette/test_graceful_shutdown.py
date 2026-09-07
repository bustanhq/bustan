"""A real server, on a real port, taken down the way a deployment takes one down.

Nothing here drives the application in process. What matters about a shutdown is what
happens to a request that is already on the wire when the process is told to stop, and
an in-process client cannot be in that position: it has no socket to be dropped, no
server to be signalled and no port to be released. So every test starts Uvicorn on a
loopback port, speaks HTTP/1.1 to it over a socket, and asserts on what the caller
holding that socket receives.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import socket
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, suppress
from typing import cast

import pytest

from bustan import Controller, Get, Module, create_app
from bustan.adapters.starlette import StarletteAdapter
from bustan.adapters.starlette.shutdown import DrainGate
from bustan.app.application import Application

# Long enough that a slow machine still finishes a shutdown inside it, short enough that
# a test which has genuinely hung fails rather than sits there.
_PATIENCE_SECONDS = 15.0


@pytest.fixture
def absorbed_signals() -> Iterator[None]:
    """Keep the signals these tests send from reaching the interpreter's own handlers.

    Uvicorn restores the handlers it replaced and then re-raises the signal it caught,
    so that a process it was embedded in still learns what happened. A test signalling
    itself would therefore deliver a second ``SIGTERM`` to whatever pytest was started
    with, which is a terminated test run. Absorbing both signals for the length of the
    test keeps the one it sends inside it.
    """

    handled = (signal.SIGINT, signal.SIGTERM)
    previous = {number: signal.signal(number, lambda *_arguments: None) for number in handled}
    try:
        yield
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)


def _free_port() -> int:
    """Return a loopback port nothing is listening on."""

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _port_is_free(port: int) -> bool:
    """Return whether a listener can bind this port, which is what stopping must leave.

    The probe asks for address reuse, as every server does, so a connection the stopped
    server left in ``TIME_WAIT`` is not read as the port still being held. A port an
    actual listener is bound to is refused either way, which is the case being asserted.
    """

    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
        return True


async def _request(port: int, path: str) -> tuple[int, bytes]:
    """Send one request over its own connection and read the whole answer back."""

    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(
            f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n".encode("latin-1")
        )
        await writer.drain()
        raw = await reader.read()
    finally:
        writer.close()
        with suppress(OSError):
            await writer.wait_closed()

    head, _separator, body = raw.partition(b"\r\n\r\n")
    if not head:
        raise AssertionError("the server closed the connection without answering")
    return int(head.split()[1]), body


async def _wait_until_accepting(port: int) -> None:
    """Block until the server has bound the port, so a request cannot arrive too early."""

    deadline = time.monotonic() + _PATIENCE_SECONDS
    while time.monotonic() < deadline:
        try:
            _reader, writer = await asyncio.open_connection("127.0.0.1", port)
        except OSError:
            await asyncio.sleep(0.02)
            continue
        writer.close()
        with suppress(OSError):
            await writer.wait_closed()
        return
    raise AssertionError(f"the server never began listening on port {port}")


def _slow_application(hold: asyncio.Event, entered: asyncio.Event) -> tuple[Application, list[str]]:
    """Build an application with one route that is still running when the signal lands.

    The list that comes back is what the shutdown hook was told, so a test can assert on
    the signal name the framework passed rather than on the fact that it ran at all.
    """

    announced: list[str] = []

    @Controller("/app")
    class SlowController:
        @Get("/slow")
        async def slow(self) -> dict[str, str]:
            entered.set()
            await hold.wait()
            return {"served": "yes"}

        @Get("/quick")
        def quick(self) -> dict[str, str]:
            return {"served": "immediately"}

    @Module(controllers=[SlowController])
    class AppModule:
        def on_application_shutdown(self, signal_name: str | None) -> None:
            announced.append(str(signal_name))

    return create_app(AppModule), announced


@asynccontextmanager
async def _serving(
    application: Application, *, drain_timeout: float | None = None
) -> AsyncIterator[tuple[int, asyncio.Task[None]]]:
    """Serve one application on a free port, and leave nothing running afterwards."""

    port = _free_port()
    serving: asyncio.Task[None] = asyncio.create_task(
        application.listen(port, drain_timeout=drain_timeout, log_level="warning")
    )
    await _wait_until_accepting(port)
    try:
        yield port, serving
    finally:
        if not serving.done():
            await application.close()
        await asyncio.wait_for(serving, timeout=_PATIENCE_SECONDS)


@pytest.mark.anyio
async def test_a_request_in_flight_is_answered_when_the_process_is_signalled(
    absorbed_signals: None,
) -> None:
    hold, entered = asyncio.Event(), asyncio.Event()
    application, announced = _slow_application(hold, entered)

    async with _serving(application) as (port, serving):
        pending = asyncio.create_task(_request(port, "/app/slow"))
        await asyncio.wait_for(entered.wait(), timeout=_PATIENCE_SECONDS)

        os.kill(os.getpid(), signal.SIGTERM)
        # The handler is released only after the signal has been delivered, so the
        # response asserted on below was written by a process already told to stop.
        await asyncio.sleep(0.2)
        hold.set()

        status, body = await asyncio.wait_for(pending, timeout=_PATIENCE_SECONDS)
        await asyncio.wait_for(serving, timeout=_PATIENCE_SECONDS)

    assert status == 200
    assert json.loads(body) == {"served": "yes"}
    assert announced == ["SIGTERM"]


@pytest.mark.anyio
async def test_a_request_arriving_after_the_signal_is_refused_rather_than_half_served(
    absorbed_signals: None,
) -> None:
    hold, entered = asyncio.Event(), asyncio.Event()
    application, _announced = _slow_application(hold, entered)

    async with _serving(application, drain_timeout=_PATIENCE_SECONDS) as (port, serving):
        pending = asyncio.create_task(_request(port, "/app/slow"))
        await asyncio.wait_for(entered.wait(), timeout=_PATIENCE_SECONDS)

        os.kill(os.getpid(), signal.SIGTERM)
        refused_status, refused_body = await asyncio.wait_for(
            _request(port, "/app/quick"), timeout=_PATIENCE_SECONDS
        )
        # What a readiness check on this process reports while it is on its way down,
        # and how many callers it is still finishing with.
        adapter = cast(StarletteAdapter, application.get_http_adapter())
        assert adapter.draining is True
        assert adapter.in_flight == 1

        hold.set()
        served_status, _served_body = await asyncio.wait_for(pending, timeout=_PATIENCE_SECONDS)
        await asyncio.wait_for(serving, timeout=_PATIENCE_SECONDS)

    assert refused_status == 503
    assert json.loads(refused_body)["title"] == "Service Unavailable"
    assert served_status == 200


@pytest.mark.anyio
async def test_a_request_that_outlasts_the_drain_window_does_not_hold_the_server_open(
    absorbed_signals: None,
) -> None:
    hold, entered = asyncio.Event(), asyncio.Event()
    application, announced = _slow_application(hold, entered)

    async with _serving(application, drain_timeout=0.1) as (port, serving):
        pending = asyncio.create_task(_request(port, "/app/slow"))
        await asyncio.wait_for(entered.wait(), timeout=_PATIENCE_SECONDS)

        # Nothing ever sets ``hold``: this request would run for as long as the test
        # does, so a shutdown that waited on it is a shutdown that never finishes.
        began = time.monotonic()
        os.kill(os.getpid(), signal.SIGTERM)
        await asyncio.wait_for(serving, timeout=_PATIENCE_SECONDS)
        elapsed = time.monotonic() - began

        pending.cancel()
        with suppress(asyncio.CancelledError, OSError, AssertionError):
            await pending

    assert elapsed < _PATIENCE_SECONDS
    assert announced == ["SIGTERM"]
    assert _port_is_free(port)


@pytest.mark.anyio
async def test_closing_an_application_stops_its_server_and_frees_the_port() -> None:
    hold, entered = asyncio.Event(), asyncio.Event()
    hold.set()
    application, announced = _slow_application(hold, entered)

    port = _free_port()
    serving: asyncio.Task[None] = asyncio.create_task(application.listen(port, log_level="warning"))
    await _wait_until_accepting(port)
    assert not _port_is_free(port)

    await application.close()

    assert _port_is_free(port)
    await asyncio.wait_for(serving, timeout=_PATIENCE_SECONDS)
    # No signal asked for this one, so the hooks are told that none did.
    assert announced == ["None"]


@pytest.mark.anyio
async def test_closing_an_application_that_never_served_still_runs_its_teardown() -> None:
    hold, entered = asyncio.Event(), asyncio.Event()
    hold.set()
    application, announced = _slow_application(hold, entered)

    await application.init()
    await application.close()

    assert announced == ["None"]


@pytest.mark.anyio
async def test_the_drain_gate_reports_idle_only_once_every_request_has_finished() -> None:
    gate = DrainGate()

    assert gate.admit() is True
    assert gate.in_flight == 1
    assert await gate.wait_until_idle(0.05) is False
    # A window of zero is a caller saying it will not wait at all, which is an answer
    # about the requests in flight rather than an instruction to wait without a limit.
    assert await gate.wait_until_idle(0) is False

    gate.release()

    assert gate.in_flight == 0
    assert await gate.wait_until_idle(None) is True


@pytest.mark.anyio
async def test_the_drain_gate_stays_closed_once_it_has_begun_draining() -> None:
    gate = DrainGate()
    assert gate.admit() is True
    gate.begin_drain()

    assert gate.draining is True
    assert gate.admit() is False

    gate.release()

    assert await gate.wait_until_idle(_PATIENCE_SECONDS) is True
    assert gate.draining is True
