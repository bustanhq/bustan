"""Mechanics shared by every benchmark: build an application, drive one request.

Nothing here measures anything. It exists so that each benchmark module states only the
shape it is measuring, and so that every benchmark pays the same cost for the parts that
are not the subject of the measurement.

The transport is the raw ASGI adapter and the event loop belongs to the driver, so what a
measurement covers is the framework's own work - routing, injection, the pipeline,
serialization - and not a web server, a socket, an HTTP parser or a thread hand-off.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from bustan import create_app
from bustan.adapters.asgi import AsgiAdapter

if TYPE_CHECKING:
    from collections.abc import Sequence

    from bustan.adapters.asgi.types import AsgiApp
    from bustan.app.application import Application

# What a request that never asked to be anything else says about itself. Every benchmark
# sends the same one, so a difference between two of them is a difference in the
# application rather than in the request.
_DEFAULT_HEADERS: tuple[tuple[bytes, bytes], ...] = ((b"host", b"benchmark"),)
_EMPTY_BODY: dict[str, Any] = {"type": "http.request", "body": b"", "more_body": False}


def build_application(root_module: type[object]) -> tuple[Application, AsgiApp]:
    """Build an application on the raw ASGI adapter and return it with its ASGI callable.

    The adapter is given no lifespan, so the returned application has not started yet;
    the driver starts it, on the loop the requests will run on.
    """

    adapter = AsgiAdapter()
    application = create_app(root_module, adapter=adapter)
    return application, adapter.get_instance()


def build_scope(path: str, headers: Sequence[tuple[bytes, bytes]] = ()) -> dict[str, Any]:
    """Return the ASGI connection scope for one GET request to ``path``."""

    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "root_path": "",
        "headers": [*_DEFAULT_HEADERS, *headers],
        "client": ("127.0.0.1", 51000),
        "server": ("benchmark", 80),
    }


async def _receive() -> dict[str, Any]:
    return _EMPTY_BODY


class RequestDriver:
    """Serves requests to one application on a private event loop, one at a time.

    Built as a context manager so that application startup and every request it serves
    run on the same loop, which is what a server would do and what anything the
    application built during startup expects.

    ``send_request`` is the callable a benchmark times. It returns the response status so
    that a benchmark can assert the application actually served the route rather than
    timing an error path that happens to be fast.
    """

    __slots__ = ("_application", "_asgi", "_loop", "_scope")

    def __init__(self, root_module: type[object], path: str) -> None:
        self._application, self._asgi = build_application(root_module)
        self._scope = build_scope(path)
        self._loop = asyncio.new_event_loop()

    def __enter__(self) -> RequestDriver:
        self._loop.run_until_complete(self._application.init())
        return self

    def __exit__(self, *exception: object) -> None:
        try:
            self._loop.run_until_complete(self._application.close())
        finally:
            self._loop.close()

    def send_request(self) -> int:
        """Serve one request and return the status the application answered with."""

        return self._loop.run_until_complete(self._serve())

    async def _serve(self) -> int:
        status = 0

        async def send(message: dict[str, Any]) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])

        # A fresh mapping per request because an ASGI application owns the scope it is
        # given: this one writes the application and the request state into it.
        await self._asgi(dict(self._scope), _receive, send)
        return status
