"""The ASGI adapter implements the port and nothing more."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from bustan.adapters.asgi import AsgiAdapter, AsgiApplication, AsgiTestClient
from bustan.adapters.asgi.requests import AsgiHttpRequest
from bustan.adapters.asgi.responses import AsgiResponse, AsgiStreamResponse
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
