"""The in-process client that drives an application without a socket."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, cast

import pytest

from bustan.adapters.asgi.application import AsgiApplication, Lifespan
from bustan.adapters.asgi.responses import AsgiResponse
from bustan.adapters.asgi.testclient import AsgiTestClient
from bustan.contracts import AdapterRoute, HttpRequest, HttpResponse, QueryParams

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


async def _echo(request: HttpRequest) -> HttpResponse:
    return HttpResponse.json(
        {
            "method": request.method,
            "path": request.path,
            "query": sorted(cast("QueryParams", request.query_params).multi_items()),
            "host": request.headers["host"],
            "user_agent": request.headers["user-agent"],
            "cookies": dict(request.cookies),
            "body": (await request.body()).decode(),
        }
    )


async def _set_cookie(_request: HttpRequest) -> HttpResponse:
    return HttpResponse(status_code=204, headers={"set-cookie": "session=abc; Path=/"}, body=b"")


async def _drop_cookie(_request: HttpRequest) -> HttpResponse:
    return HttpResponse(status_code=204, headers={"set-cookie": "session=; Path=/"}, body=b"")


async def _redirect(_request: HttpRequest) -> HttpResponse:
    return HttpResponse(status_code=307, headers={"location": "/echo"}, body=b"")


async def _see_other(_request: HttpRequest) -> HttpResponse:
    return HttpResponse(status_code=303, headers={"location": "/echo"}, body=b"")


async def _loop(_request: HttpRequest) -> HttpResponse:
    return HttpResponse(status_code=307, headers={"location": "/loop"}, body=b"")


def _client(lifespan: Lifespan | None = None) -> AsgiTestClient:
    application = AsgiApplication(lifespan=lifespan)
    application.register(
        [
            AdapterRoute(
                path="/echo",
                methods=("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"),
                handler=_echo,
            ),
            AdapterRoute(path="/cookie", methods=("GET",), handler=_set_cookie),
            AdapterRoute(path="/cookie/drop", methods=("GET",), handler=_drop_cookie),
            AdapterRoute(path="/redirect", methods=("GET", "POST"), handler=_redirect),
            AdapterRoute(path="/see-other", methods=("POST",), handler=_see_other),
            AdapterRoute(path="/loop", methods=("GET",), handler=_loop),
        ]
    )
    return AsgiTestClient(application)


def test_a_request_arrives_with_the_client_name_and_host_it_says_it_has() -> None:
    payload = _client().get("/echo").json()

    assert payload["host"] == "testserver"
    assert payload["user_agent"] == "bustan-asgi-testclient"


def test_query_parameters_can_be_written_into_the_path_or_passed_separately() -> None:
    client = _client()

    assert client.get("/echo?tag=a&tag=b").json()["query"] == [["tag", "a"], ["tag", "b"]]
    assert client.get("/echo", params={"page": "2"}).json()["query"] == [["page", "2"]]
    assert client.get("/echo?tag=a", params={"page": "2"}).json()["query"] == [
        ["page", "2"],
        ["tag", "a"],
    ]


def test_a_json_body_is_encoded_and_declared_as_json() -> None:
    response = _client().post("/echo", json={"name": "Ada"})

    assert response.json()["body"] == '{"name": "Ada"}'


def test_form_data_is_encoded_and_declared_as_a_form() -> None:
    response = _client().post("/echo", data={"name": "Ada"})

    assert response.json()["body"] == "name=Ada"


def test_a_body_can_be_sent_as_text_or_as_bytes() -> None:
    client = _client()

    assert client.put("/echo", content="raw").json()["body"] == "raw"
    assert client.patch("/echo", content=b"raw").json()["body"] == "raw"


def test_every_method_the_client_offers_reaches_the_handler() -> None:
    client = _client()

    assert client.get("/echo").json()["method"] == "GET"
    assert client.delete("/echo").json()["method"] == "DELETE"
    assert client.options("/echo").json()["method"] == "OPTIONS"
    assert client.head("/echo").status_code == 200


def test_headers_the_caller_set_override_the_defaults() -> None:
    response = _client().get("/echo", headers={"Host": "example.test"})

    assert response.json()["host"] == "example.test"


def test_a_cookie_a_response_set_is_sent_with_the_next_request() -> None:
    client = _client()

    client.get("/cookie")

    assert client.cookies == {"session": "abc"}
    assert client.get("/echo").json()["cookies"] == {"session": "abc"}


def test_a_cookie_a_response_cleared_stops_being_sent() -> None:
    client = _client()
    client.get("/cookie")

    client.get("/cookie/drop")

    assert client.cookies == {}


def test_cookies_passed_to_one_request_are_sent_only_with_it() -> None:
    client = _client()

    assert client.get("/echo", cookies={"theme": "dark"}).json()["cookies"] == {"theme": "dark"}
    assert client.get("/echo").json()["cookies"] == {}


def test_a_redirect_is_followed_and_the_method_is_kept() -> None:
    response = _client().post("/redirect", json={"name": "Ada"})

    assert response.status_code == 200
    assert response.json()["method"] == "POST"
    assert response.url == "/echo"


def test_a_see_other_redirect_turns_the_followed_request_into_a_get() -> None:
    response = _client().post("/see-other", json={"name": "Ada"})

    assert response.json()["method"] == "GET"
    assert response.json()["body"] == ""


def test_a_redirect_is_returned_unfollowed_when_the_caller_asked_for_that() -> None:
    response = _client().get("/redirect", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/echo"


def test_a_redirect_that_never_ends_is_given_up_on() -> None:
    with pytest.raises(RuntimeError, match="Exceeded 20 redirects"):
        _client().get("/loop")


def test_a_response_reports_its_body_as_bytes_text_and_json() -> None:
    response = _client().get("/echo")

    assert response.content.startswith(b"{")
    assert response.text.startswith("{")
    assert response.json()["path"] == "/echo"
    assert repr(response) == "AsgiTestResponse(status_code=200, url='/echo')"


def test_a_client_used_as_a_context_manager_runs_the_applications_lifespan() -> None:
    events: list[str] = []

    @asynccontextmanager
    async def lifespan(_app: AsgiApplication) -> AsyncIterator[None]:
        events.append("startup")
        yield
        events.append("shutdown")

    with _client(lifespan=lifespan) as client:
        assert client.get("/echo").status_code == 200
        assert events == ["startup"]

    assert events == ["startup", "shutdown"]


def test_a_lifespan_that_fails_to_start_releases_the_loop_it_was_starting_on() -> None:
    @asynccontextmanager
    async def lifespan(_app: AsgiApplication) -> AsyncIterator[None]:
        raise RuntimeError("no database")
        yield

    client = _client(lifespan=lifespan)

    with pytest.raises(RuntimeError, match="no database"), client:
        pass  # pragma: no cover - entering the block is what raises

    assert client.get("/echo").status_code == 200


def test_a_client_can_drive_an_application_that_is_not_an_adapters() -> None:
    async def app(scope, receive, send) -> None:
        await AsgiResponse(body=b"bare", media_type="text/plain")(send)

    response = AsgiTestClient(app).get("/anything")

    assert response.text == "bare"
