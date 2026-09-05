"""The Starlette adapter implements the port and nothing more."""

from __future__ import annotations

import builtins
from typing import TYPE_CHECKING, Any, cast

import pytest
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from bustan.adapters.starlette import StarletteAdapter, StarletteHttpRequest
from bustan.adapters.starlette.routes import build_starlette_routes
from bustan.contracts import AdapterRoute, HttpRequest, HttpResponse

if TYPE_CHECKING:
    from tests.conftest import RequestFactory


async def _handler(request: HttpRequest) -> HttpResponse:
    return HttpResponse.json({"path": request.path}, status_code=201)


def test_the_adapter_owns_one_starlette_application() -> None:
    application = Starlette()

    assert StarletteAdapter(application).get_instance() is application
    assert isinstance(StarletteAdapter().get_instance(), Starlette)


def test_the_adapter_converts_in_both_directions(build_request: RequestFactory) -> None:
    adapter = StarletteAdapter()
    native = build_request(path="/users")

    converted = adapter.from_native_request(native)

    assert isinstance(converted, StarletteHttpRequest)
    assert converted.path == "/users"

    written = adapter.to_native_response(HttpResponse.json({"ok": True}, status_code=202))

    assert isinstance(written, Response)
    assert written.status_code == 202


def test_registered_routes_serve_the_neutral_handler() -> None:
    adapter = StarletteAdapter()

    adapter.register_routes(
        [
            AdapterRoute(
                path="/users",
                methods=("GET",),
                name="users",
                handler=_handler,
                attributes=(("bustan_probe", "left-behind"),),
            )
        ]
    )

    registered = adapter.get_instance().routes[0]

    assert isinstance(registered, Route)
    assert registered.path == "/users"
    # The attribute is attached dynamically, so it is read back the same way.
    assert getattr(registered, "bustan_probe", None) == "left-behind"


def test_a_prebuilt_registration_is_registered_as_it_stands() -> None:
    adapter = StarletteAdapter()
    prebuilt = Route("/openapi.json", endpoint=lambda request: Response(), methods=["GET"])

    adapter.register_routes(
        [AdapterRoute(path="/openapi.json", methods=("GET",), registration=prebuilt)]
    )

    assert adapter.get_instance().routes[0] is prebuilt


def test_a_route_with_neither_a_handler_nor_a_registration_is_refused() -> None:
    with pytest.raises(ValueError, match="neither a handler nor a registration"):
        build_starlette_routes([AdapterRoute(path="/nothing", methods=("GET",))])


def test_middleware_is_added_to_the_underlying_application() -> None:
    adapter = StarletteAdapter()

    class NoopMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            return await call_next(request)

    adapter.add_middleware(NoopMiddleware)

    assert any(
        middleware.cls is NoopMiddleware
        for middleware in cast(Any, adapter.get_instance()).user_middleware
    )


def test_the_test_client_drives_the_application_in_process() -> None:
    adapter = StarletteAdapter()
    adapter.register_routes(
        [AdapterRoute(path="/users", methods=("GET",), name="users", handler=_handler)]
    )

    client = cast(Any, adapter.create_test_client())
    response = client.get("/users")

    assert response.status_code == 201
    assert response.json() == {"path": "/users"}


@pytest.mark.anyio
async def test_stopping_an_adapter_that_never_started_does_nothing() -> None:
    adapter = StarletteAdapter()

    assert await adapter.stop() is None


@pytest.mark.anyio
async def test_stopping_a_running_adapter_asks_its_server_to_exit() -> None:
    adapter = StarletteAdapter()

    class FakeServer:
        should_exit = False

    server = FakeServer()
    cast(Any, adapter)._server = server

    await adapter.stop()

    assert server.should_exit is True


@pytest.mark.anyio
async def test_the_adapter_serves_an_asgi_connection_it_is_handed() -> None:
    adapter = StarletteAdapter()
    adapter.register_routes(
        [AdapterRoute(path="/users", methods=("GET",), name="users", handler=_handler)]
    )
    sent: list[dict[str, object]] = []

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, object]) -> None:
        sent.append(message)

    await adapter(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/users",
            "raw_path": b"/users",
            "query_string": b"",
            "headers": [(b"host", b"testserver")],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
        },
        receive,
        send,
    )

    assert sent[0]["status"] == 201


@pytest.mark.anyio
async def test_starting_runs_a_uvicorn_server_and_forgets_it_afterwards(monkeypatch) -> None:
    import uvicorn

    served: list[uvicorn.Config] = []

    async def fake_serve(self: uvicorn.Server, sockets: object = None) -> None:
        served.append(self.config)

    monkeypatch.setattr(uvicorn.Server, "serve", fake_serve)
    adapter = StarletteAdapter()

    await adapter.start(8123, host="0.0.0.0", reload=False, log_level="warning")

    assert served[0].port == 8123
    assert served[0].host == "0.0.0.0"
    assert cast(Any, adapter)._server is None


@pytest.mark.anyio
async def test_listen_is_the_same_entry_point_under_the_application_wrappers_name(
    monkeypatch,
) -> None:
    import uvicorn

    served: list[int] = []

    async def fake_serve(self: uvicorn.Server, sockets: object = None) -> None:
        served.append(self.config.port)

    monkeypatch.setattr(uvicorn.Server, "serve", fake_serve)

    await StarletteAdapter().listen(8124)

    assert served == [8124]


def _failing_import(error: BaseException):
    real_import = builtins.__import__

    def fail_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "starlette.testclient":
            raise error
        return real_import(name, globals, locals, fromlist, level)

    return fail_import


def test_a_missing_test_client_dependency_is_reported_as_such(monkeypatch) -> None:
    monkeypatch.setattr(
        builtins,
        "__import__",
        _failing_import(ModuleNotFoundError("No module named 'httpx'", name="httpx")),
    )

    with pytest.raises(ImportError, match="optional 'httpx' dependency"):
        StarletteAdapter().create_test_client()


def test_a_test_client_import_failure_of_another_kind_is_left_alone(monkeypatch) -> None:
    monkeypatch.setattr(
        builtins,
        "__import__",
        _failing_import(ModuleNotFoundError("No module named 'other'", name="other")),
    )

    with pytest.raises(ModuleNotFoundError, match="other"):
        StarletteAdapter().create_test_client()


def test_a_runtime_complaint_about_httpx_is_reported_as_a_missing_dependency(monkeypatch) -> None:
    monkeypatch.setattr(
        builtins,
        "__import__",
        _failing_import(RuntimeError("the testclient module requires the httpx package")),
    )

    with pytest.raises(ImportError, match="optional 'httpx' dependency"):
        StarletteAdapter().create_test_client()


def test_an_unrelated_runtime_failure_while_importing_is_left_alone(monkeypatch) -> None:
    monkeypatch.setattr(builtins, "__import__", _failing_import(RuntimeError("something else")))

    with pytest.raises(RuntimeError, match="something else"):
        StarletteAdapter().create_test_client()
