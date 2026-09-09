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


def test_the_adapter_declares_the_request_type_it_produces(
    build_request: RequestFactory,
) -> None:
    """Both directions are declared: what it converts, and what it hands over.

    A handler naming this transport's request type is handed exactly this class, so this
    is what makes such an annotation checkable rather than a claim about the deployment.
    """

    adapter = StarletteAdapter()
    wrapped = adapter.from_native_request(build_request(path="/users"))

    assert adapter.native_request_type is Request
    assert isinstance(wrapped.native_request, adapter.native_request_type)


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


def test_a_route_carrying_no_handler_is_refused_by_name() -> None:
    # A handler is the whole of what the port hands an adapter, so a route without one
    # cannot serve a request and is refused rather than registered as a dead path.
    with pytest.raises(ValueError, match="/nothing carries no handler"):
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


def _refusing_client(methods: list[str]) -> Any:
    """A client for an application serving one route, so any other request is refused."""

    adapter = StarletteAdapter()
    adapter.register_routes(
        [AdapterRoute(path="/orders", methods=tuple(methods), handler=_handler, name="orders")]
    )
    return cast(Any, adapter.create_test_client())


def test_a_path_this_router_does_not_serve_is_refused_in_the_framework_error_model() -> None:
    """The transport's own 404 would be plain text, which is outside the error model.

    A caller reading the documented model meets this refusal before any other, so the
    transport answering it its own way is the one place a documented universal breaks.
    """

    with _refusing_client(["GET"]) as client:
        response = client.get("/absent")

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json() == {
        "type": "https://bustan.dev/problems/not-found",
        "title": "Not Found",
        "status": 404,
        "detail": "Not Found",
        "instance": "/absent",
        "code": "not-found",
    }


def test_a_method_this_router_does_not_serve_keeps_the_allow_it_worked_out() -> None:
    with _refusing_client(["GET", "POST"]) as client:
        response = client.delete("/orders")

    assert response.status_code == 405
    assert response.headers["content-type"] == "application/problem+json"
    assert response.headers["allow"] == "GET, HEAD, POST"
    assert response.json()["code"] == "method-not-allowed"


def test_the_allow_header_does_not_depend_on_the_order_the_router_declared_methods() -> None:
    """Starlette holds a route's methods in a set, which has no order to promise.

    The header a caller reads has to be the same on every transport, so an application
    that changed adapters, or a set that iterated differently, cannot change it.
    """

    with _refusing_client(["POST", "GET"]) as client:
        declared_one_way = client.delete("/orders").headers["allow"]
    with _refusing_client(["GET", "POST"]) as client:
        declared_the_other = client.delete("/orders").headers["allow"]

    assert declared_one_way == declared_the_other == "GET, HEAD, POST"


def test_an_application_handed_in_is_given_the_error_model_too() -> None:
    """The error model is the framework's promise, so it does not depend on which
    Starlette application the adapter was handed."""

    application = Starlette()
    adapter = StarletteAdapter(application)
    adapter.register_routes(
        [AdapterRoute(path="/orders", methods=("GET",), handler=_handler, name="orders")]
    )

    with cast(Any, adapter.create_test_client()) as client:
        assert client.get("/absent").headers["content-type"] == "application/problem+json"


def _client_serving(path: str, methods: tuple[str, ...] = ("GET",)) -> Any:
    """A client for an application serving one route, at the path and methods given."""

    adapter = StarletteAdapter()
    adapter.register_routes(
        [AdapterRoute(path=path, methods=methods, handler=_handler, name="route")]
    )
    return cast(Any, adapter.create_test_client())


def test_one_trailing_slash_is_redirected_to_the_relative_path_a_route_serves() -> None:
    """An absolute location can only be built from the caller's own Host header.

    That header names the wrong host behind any proxy that terminates TLS, and it is
    client-controlled input reflected into a redirect wherever it happens to be right.
    """

    with _client_serving("/shop/orders") as client:
        response = client.get("/shop/orders/", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/shop/orders"
    assert "content-type" not in response.headers
    assert response.content == b""


def test_two_trailing_slashes_are_refused_rather_than_rewritten() -> None:
    """``/shop/orders//`` is a path of its own, not the slashed spelling of a route.

    A transport that stripped every trailing slash would answer a request the caller
    never sent, and would report a resource at a path nothing is registered at.
    """

    with _client_serving("/shop/orders") as client:
        response = client.get("/shop/orders//", follow_redirects=False)

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["instance"] == "/shop/orders//"


def test_a_redirect_keeps_the_query_string_the_caller_sent() -> None:
    with _client_serving("/shop/orders") as client:
        response = client.get("/shop/orders/?page=2", follow_redirects=False)

    assert response.headers["location"] == "/shop/orders?page=2"


def test_a_redirect_is_built_from_the_target_the_caller_wrote() -> None:
    """A location built from the decoded path would carry a space loose in a header."""

    with _client_serving("/users/{user_id}") as client:
        response = client.get("/users/John%20Doe/", follow_redirects=False)

    assert response.headers["location"] == "/users/John%20Doe"


def test_a_route_registered_with_a_trailing_slash_answers_the_spelling_without_one() -> None:
    """The flip works both ways round, because either spelling can be the registered one."""

    with _client_serving("/shop/orders/") as client:
        response = client.get("/shop/orders", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/shop/orders/"


def test_a_path_only_a_slash_from_a_route_that_refuses_the_method_is_still_redirected() -> None:
    """The caller is sent where the framework's 405 names the methods it could send."""

    with _client_serving("/shop/orders", ("GET",)) as client:
        response = client.post("/shop/orders/", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/shop/orders"


def test_the_root_path_is_refused_rather_than_redirected_to_an_empty_location() -> None:
    """Flipping the slash off ``/`` leaves nothing to send a caller to."""

    with _client_serving("/shop/orders") as client:
        response = client.get("/", follow_redirects=False)

    assert response.status_code == 404
    assert response.json()["instance"] == "/"


def test_an_application_handed_in_has_its_own_slash_redirect_overruled() -> None:
    """The shape of a redirect is the framework's promise, not the transport's.

    Starlette decides its own redirect in the router, before the endpoint whose refusal
    the error-model handlers answer, so the only place to refuse it is the router itself.
    """

    application = Starlette()
    adapter = StarletteAdapter(application)
    adapter.register_routes(
        [AdapterRoute(path="/orders", methods=("GET",), handler=_handler, name="orders")]
    )

    assert application.router.redirect_slashes is False

    with cast(Any, adapter.create_test_client()) as client:
        response = client.get("/orders/", follow_redirects=False)

    assert response.headers["location"] == "/orders"
