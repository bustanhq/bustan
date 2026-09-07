"""The ASGI adapter implements the port and nothing more."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import pytest

from bustan import Controller, Module, Post, create_app
from bustan.adapters.asgi import AsgiAdapter, AsgiApplication, AsgiTestClient
from bustan.adapters.asgi.requests import AsgiHttpRequest
from bustan.adapters.asgi.responses import AsgiResponse, AsgiStreamResponse
from bustan.adapters.asgi.testclient import AsgiTestResponse
from bustan.contracts import (
    AbstractHttpAdapter,
    AdapterCapabilities,
    AdapterRoute,
    HttpRequest,
    HttpResponse,
    HttpStreamResponse,
)

if TYPE_CHECKING:
    from bustan.adapters.asgi.types import AsgiApp, Message, Receive, Scope, Send

    from .conftest import ReceiveFactory, ScopeFactory


async def _ok(_request: HttpRequest) -> HttpResponse:
    return HttpResponse.json({"ok": True})


def _notes_application(adapter: AsgiAdapter, served: list[str]) -> None:
    """Build one application on *adapter* whose only route needs the request body."""

    @Controller("/notes")
    class NotesController:
        @Post("/")
        def create(self, title: str) -> dict[str, str]:
            served.append(title)
            return {"title": title}

    @Module(controllers=[NotesController])
    class AppModule:
        pass

    create_app(AppModule, adapter=adapter)


def _post_streamed_body(adapter: AsgiAdapter, size: int) -> AsgiTestResponse:
    """Post a JSON body of *size* filler bytes, sent without declaring a length."""

    with adapter.create_test_client() as client:
        return client.post(
            "/notes",
            headers={"content-type": "application/json"},
            content=iter([b'{"title":"', b"x" * size, b'"}']),
        )


def test_the_adapter_names_the_transport_it_binds_and_what_it_can_serve() -> None:
    adapter = AsgiAdapter()

    assert isinstance(adapter, AbstractHttpAdapter)
    assert adapter.name == "asgi"
    assert adapter.capabilities == AdapterCapabilities(
        supports_host_routing=False,
        supports_raw_body=True,
        supports_streaming_responses=True,
        supports_websocket_upgrade=False,
    )


def test_the_adapter_drives_the_application_it_was_given() -> None:
    application = AsgiApplication()

    assert AsgiAdapter(application).get_instance() is application


def test_the_adapter_builds_an_application_when_it_was_given_none() -> None:
    assert isinstance(AsgiAdapter().get_instance(), AsgiApplication)


def test_a_request_this_transport_carries_becomes_the_neutral_contract(
    build_scope: ScopeFactory, build_receive: ReceiveFactory
) -> None:
    wrapped = AsgiAdapter().from_native_request((build_scope(path="/here"), build_receive()))

    assert isinstance(wrapped, AsgiHttpRequest)
    assert wrapped.path == "/here"


def test_a_framework_response_becomes_the_response_this_transport_writes() -> None:
    adapter = AsgiAdapter()

    assert isinstance(adapter.to_native_response(HttpResponse.json({})), AsgiResponse)
    assert isinstance(
        adapter.to_native_response(HttpStreamResponse(body=[b""])), AsgiStreamResponse
    )


def test_a_body_past_what_the_transport_reads_is_refused_with_the_status_it_deserves() -> None:
    """The transport stopping is a refusal of the caller, and has to be answered as one.

    The body declares no length, so nothing can refuse it before it is read and the
    ceiling this adapter was built with is what stops it. What the caller is then told
    has to be the 413 the application's own body limit produces: a caller who sent too
    much has not caused a fault, and answering 500 both misreports what happened and
    hides that this transport is the one that refused.
    """

    served: list[str] = []
    adapter = AsgiAdapter(max_body_bytes=32)
    _notes_application(adapter, served)

    response = _post_streamed_body(adapter, 200)

    assert response.status_code == 413
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json() == {
        "type": "about:blank",
        "title": "Content Too Large",
        "status": 413,
        "detail": "The request body carries more than the 32 byte limit",
        "instance": "/notes",
    }
    assert served == []


def test_a_refused_body_is_reported_as_a_refusal_rather_than_as_an_unhandled_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    served: list[str] = []
    adapter = AsgiAdapter(max_body_bytes=32)
    _notes_application(adapter, served)

    with caplog.at_level(logging.DEBUG, logger="bustan"):
        response = _post_streamed_body(adapter, 200)

    assert response.status_code == 413
    assert [record.message for record in caplog.records if record.levelno >= logging.ERROR] == []
    assert [record.exc_info for record in caplog.records if record.exc_info is not None] == []
    assert any(
        record.levelno == logging.WARNING and "32 byte limit" in record.getMessage()
        for record in caplog.records
    )


def test_a_body_within_what_the_transport_reads_is_served_as_before() -> None:
    served: list[str] = []
    adapter = AsgiAdapter(max_body_bytes=1024)
    _notes_application(adapter, served)

    response = _post_streamed_body(adapter, 200)

    assert response.status_code == 200
    assert response.json() == {"title": "x" * 200}
    assert served == ["x" * 200]


def test_registering_routes_puts_them_on_the_application_in_order() -> None:
    adapter = AsgiAdapter()

    adapter.register_routes(
        [
            AdapterRoute(path="/first", methods=("GET",), handler=_ok),
            AdapterRoute(path="/second", methods=("GET",), handler=_ok),
        ]
    )

    assert [route.path for route in adapter.get_instance().routes] == ["/first", "/second"]


def test_middleware_added_through_the_adapter_wraps_the_application() -> None:
    seen: list[str] = []

    class Tracing:
        def __init__(self, app: AsgiApp, label: str) -> None:
            self._app, self._label = app, label

        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            seen.append(self._label)
            await self._app(scope, receive, send)

    adapter = AsgiAdapter()
    adapter.register_routes([AdapterRoute(path="/here", methods=("GET",), handler=_ok)])
    adapter.add_middleware(Tracing, label="outer")

    assert adapter.create_test_client().get("/here").status_code == 200
    assert seen == ["outer"]


def test_the_test_client_the_adapter_offers_drives_its_own_application() -> None:
    adapter = AsgiAdapter()
    adapter.register_routes([AdapterRoute(path="/here", methods=("GET",), handler=_ok)])

    client = adapter.create_test_client()

    assert isinstance(client, AsgiTestClient)
    assert client.get("/here").json() == {"ok": True}


@pytest.mark.anyio
async def test_a_connection_the_server_handed_straight_over_is_served(
    build_scope: ScopeFactory, build_receive: ReceiveFactory
) -> None:
    adapter = AsgiAdapter()
    adapter.register_routes([AdapterRoute(path="/here", methods=("GET",), handler=_ok)])
    messages: list[Message] = []

    async def send(message: Message) -> None:
        messages.append(message)

    await adapter(build_scope(path="/here"), build_receive(), send)

    assert messages[0]["status"] == 200


@pytest.mark.anyio
async def test_asking_for_a_reloader_is_refused_rather_than_quietly_ignored() -> None:
    with pytest.raises(NotImplementedError, match="no reloader"):
        await AsgiAdapter().start(0, reload=True)


@pytest.mark.anyio
async def test_stopping_a_server_that_never_started_does_nothing() -> None:
    await AsgiAdapter().stop()


@pytest.mark.anyio
async def test_the_adapter_serves_over_a_socket_until_it_is_stopped() -> None:
    adapter = AsgiAdapter()
    adapter.register_routes([AdapterRoute(path="/here", methods=("GET",), handler=_ok)])

    # ``listen`` is the name the application wrapper reaches the port by; ``start`` is
    # the one an adapter implements, and both must run the same server.
    task = asyncio.create_task(adapter.listen(0, host="127.0.0.1"))
    while adapter.get_instance() is None or not _sockets(adapter):
        await asyncio.sleep(0)
    port = _sockets(adapter)[0].getsockname()[1]

    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(b"GET /here HTTP/1.1\r\nhost: localhost\r\n\r\n")
    await writer.drain()
    answer = await reader.read()
    writer.close()

    await adapter.stop()
    await task

    assert answer.startswith(b"HTTP/1.1 200 OK\r\n")
    assert answer.endswith(b'{"ok":true}')


def _sockets(adapter: AsgiAdapter) -> tuple:
    server = getattr(adapter, "_server", None)
    return () if server is None else server.sockets
