"""The ASGI application: its router, its lifespan and the middleware around them."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import pytest

from bustan.adapters.asgi.application import AsgiApplication, Lifespan
from bustan.adapters.asgi.lifespan import LifespanFailed, LifespanRunner
from bustan.contracts import AdapterRoute, HttpRequest, HttpResponse, HttpStreamResponse

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from bustan.adapters.asgi.types import AsgiApp, Message, Receive, Scope, Send

    from .conftest import ReceiveFactory, ScopeFactory


async def _read_user(request: HttpRequest) -> HttpResponse:
    return HttpResponse.json({"user_id": request.path_params["user_id"]})


async def _stream(_request: HttpRequest) -> HttpStreamResponse:
    return HttpStreamResponse(body=[b"a", b"b"])


def _application(*routes: AdapterRoute, lifespan: Lifespan | None = None) -> AsgiApplication:
    application = AsgiApplication(lifespan=lifespan)
    application.register(routes)
    return application


def _plan(path: str, methods: tuple[str, ...] = ("GET",), handler=_read_user) -> AdapterRoute:
    return AdapterRoute(path=path, methods=methods, name="route", handler=handler)


async def _call(app: AsgiApp, scope: Scope, receive: Receive) -> tuple[int, dict[str, str], bytes]:
    messages: list[Message] = []

    async def send(message: Message) -> None:
        messages.append(message)

    await app(scope, receive, send)
    start = messages[0]
    headers = {name.decode(): value.decode() for name, value in start["headers"]}
    body = b"".join(message.get("body", b"") for message in messages[1:])
    return start["status"], headers, body


@pytest.mark.anyio
async def test_a_matching_request_reaches_the_handler_with_its_path_parameters(
    build_scope: ScopeFactory, build_receive: ReceiveFactory
) -> None:
    application = _application(_plan("/users/{user_id}"))

    status, _headers, body = await _call(application, build_scope(path="/users/7"), build_receive())

    assert status == 200
    assert body == b'{"user_id":"7"}'


@pytest.mark.anyio
async def test_a_path_no_route_answers_is_answered_by_the_transport_itself(
    build_scope: ScopeFactory, build_receive: ReceiveFactory
) -> None:
    application = _application(_plan("/users/{user_id}"))

    status, headers, body = await _call(application, build_scope(path="/orders"), build_receive())

    assert (status, body) == (404, b"Not Found")
    assert headers["content-type"] == "text/plain; charset=utf-8"


@pytest.mark.anyio
async def test_a_method_no_route_answers_reports_the_methods_that_do(
    build_scope: ScopeFactory, build_receive: ReceiveFactory
) -> None:
    application = _application(_plan("/users", ("POST",)))

    status, headers, body = await _call(
        application, build_scope(method="DELETE", path="/users"), build_receive()
    )

    assert (status, body) == (405, b"Method Not Allowed")
    assert headers["allow"] == "POST"


@pytest.mark.anyio
async def test_a_trailing_slash_is_redirected_with_the_query_string_kept(
    build_scope: ScopeFactory, build_receive: ReceiveFactory
) -> None:
    application = _application(_plan("/users/{user_id}"))

    status, headers, _body = await _call(
        application, build_scope(path="/users/7/", query_string=b"page=2"), build_receive()
    )

    assert status == 307
    assert headers["location"] == "/users/7?page=2"


@pytest.mark.anyio
async def test_a_head_request_carries_the_headers_of_its_get_and_none_of_the_body(
    build_scope: ScopeFactory, build_receive: ReceiveFactory
) -> None:
    application = _application(_plan("/users/{user_id}"))

    status, headers, body = await _call(
        application, build_scope(method="HEAD", path="/users/7"), build_receive()
    )

    assert status == 200
    assert headers["content-length"] == "15"
    assert body == b""


@pytest.mark.anyio
async def test_a_streaming_route_writes_its_chunks_through(
    build_scope: ScopeFactory, build_receive: ReceiveFactory
) -> None:
    application = _application(_plan("/stream", handler=_stream))

    _status, _headers, body = await _call(application, build_scope(path="/stream"), build_receive())

    assert body == b"ab"


@pytest.mark.anyio
async def test_the_application_attaches_itself_to_every_request_it_serves(
    build_scope: ScopeFactory, build_receive: ReceiveFactory
) -> None:
    seen: list[object] = []

    async def handler(request: HttpRequest) -> HttpResponse:
        seen.append(request.app)
        return HttpResponse.empty()

    application = _application(_plan("/here", handler=handler))
    await _call(application, build_scope(path="/here"), build_receive())

    assert seen == [application]


@pytest.mark.anyio
async def test_a_connection_this_transport_does_not_serve_is_refused_by_name(
    build_scope: ScopeFactory, build_receive: ReceiveFactory
) -> None:
    scope = build_scope()
    scope["type"] = "websocket"

    with pytest.raises(NotImplementedError, match="not 'websocket'"):
        await _call(_application(), scope, build_receive())


@pytest.mark.anyio
async def test_middleware_added_last_sees_a_request_first(
    build_scope: ScopeFactory, build_receive: ReceiveFactory
) -> None:
    order: list[str] = []

    class Tracing:
        def __init__(self, app: AsgiApp, label: str) -> None:
            self._app, self._label = app, label

        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            order.append(self._label)
            await self._app(scope, receive, send)

    application = _application(_plan("/users/{user_id}"))
    application.add_middleware(Tracing, label="first")
    application.add_middleware(Tracing, label="second")

    await _call(application, build_scope(path="/users/7"), build_receive())

    assert order == ["second", "first"]


@pytest.mark.anyio
async def test_the_lifespan_runs_startup_before_requests_and_shutdown_after() -> None:
    events: list[str] = []

    @asynccontextmanager
    async def lifespan(app: AsgiApplication) -> AsyncIterator[None]:
        events.append(f"startup:{len(app.routes)}")
        yield
        events.append("shutdown")

    application = _application(_plan("/users/{user_id}"), lifespan=lifespan)
    runner = LifespanRunner(application)

    await runner.startup()
    assert events == ["startup:1"]
    await runner.shutdown()

    assert events == ["startup:1", "shutdown"]


@pytest.mark.anyio
async def test_an_application_with_no_lifespan_still_answers_the_protocol() -> None:
    runner = LifespanRunner(_application())

    await runner.startup()
    await runner.shutdown()
    # Shutting down twice is what a client that already stopped does; it must not hang.
    await runner.shutdown()


@pytest.mark.anyio
async def test_a_startup_that_fails_is_reported_rather_than_left_to_escape() -> None:
    @asynccontextmanager
    async def lifespan(_app: AsgiApplication) -> AsyncIterator[None]:
        raise RuntimeError("no database")
        yield

    runner = LifespanRunner(_application(lifespan=lifespan))

    with pytest.raises(LifespanFailed, match="no database"):
        await runner.startup()


@pytest.mark.anyio
async def test_a_shutdown_that_fails_is_reported_rather_than_left_to_escape() -> None:
    @asynccontextmanager
    async def lifespan(_app: AsgiApplication) -> AsyncIterator[None]:
        yield
        raise RuntimeError("still draining")

    runner = LifespanRunner(_application(lifespan=lifespan))
    await runner.startup()

    with pytest.raises(LifespanFailed, match="still draining"):
        await runner.shutdown()


def test_an_application_reports_the_routes_it_registered() -> None:
    application = _application(_plan("/users/{user_id}"), _plan("/orders"))

    assert [route.path for route in application.routes] == ["/users/{user_id}", "/orders"]
    assert repr(application) == "AsgiApplication(routes=2)"


@pytest.mark.anyio
async def test_an_application_that_dies_without_answering_surfaces_what_killed_it() -> None:
    async def app(_scope: Scope, _receive: Receive, _send: Send) -> None:
        raise RuntimeError("no lifespan here")

    runner = LifespanRunner(app)

    with pytest.raises(RuntimeError, match="no lifespan here"):
        await runner.startup()


@pytest.mark.anyio
async def test_an_application_that_ends_its_lifespan_in_silence_is_reported() -> None:
    async def app(_scope: Scope, _receive: Receive, _send: Send) -> None:
        return

    runner = LifespanRunner(app)

    with pytest.raises(LifespanFailed, match="without answering"):
        await runner.startup()
