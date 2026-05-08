"""Unit tests for adapter-neutral HTTP request and response abstractions."""

from __future__ import annotations

import anyio
from starlette.responses import Response
from starlette.requests import Request

from bustan.platform.http.abstractions import (
    HttpResponse,
    StarletteHttpRequest,
    to_starlette_response,
)


def test_starlette_http_request_exposes_stable_request_fields() -> None:
    request = _build_request("POST", "/users?active=true", body=b'{"name":"Ada"}')
    wrapped = StarletteHttpRequest(request)

    assert wrapped.method == "POST"
    assert wrapped.path == "/users"
    assert wrapped.headers["host"] == "testserver"
    assert wrapped.query_params["active"] == "true"
    assert anyio.run(wrapped.body) == b'{"name":"Ada"}'


def test_http_response_mutates_status_headers_and_body_through_the_abstract_api() -> None:
    response = HttpResponse.json({"status": "ok"}, status_code=201)
    response.headers["x-test"] = "present"
    response.set_body("updated")

    adapted = to_starlette_response(response)

    assert adapted.status_code == 201
    assert adapted.headers["x-test"] == "present"
    assert adapted.body == b"updated"


def test_to_starlette_response_passes_through_native_response_instances() -> None:
    response = Response(content=b"native", status_code=202)

    assert to_starlette_response(response) is response


def _build_request(method: str, path: str, *, body: bytes = b"") -> Request:
    path_only, _, query_string = path.partition("?")
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path_only,
        "raw_path": path_only.encode("utf-8"),
        "query_string": query_string.encode("utf-8"),
        "headers": [(b"host", b"testserver")],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
        "path_params": {},
    }

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(scope, receive)
