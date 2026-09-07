"""The Starlette request wrapper must hand the framework neutral values only."""

from __future__ import annotations

from typing import TYPE_CHECKING

import anyio
import pytest
from starlette.datastructures import URL as StarletteURL
from starlette.datastructures import QueryParams as StarletteQueryParams
from starlette.datastructures import State as StarletteState
from starlette.datastructures import UploadFile as StarletteUploadFile
from starlette.requests import Request

from bustan.adapters.starlette import StarletteHttpRequest, from_starlette_request
from bustan.contracts import (
    Headers,
    HttpClientInfo,
    HttpRequest,
    QueryParams,
    RequestSlots,
    RequestState,
    Url,
)
from bustan.runtime.execution import set_request_limits
from bustan.runtime.params import (
    DEFAULT_MAX_BODY_BYTES,
    RequestBodyTooLargeError,
    RequestLimits,
)

if TYPE_CHECKING:
    from tests.conftest import AppFactory, RequestFactory


def test_the_wrapper_exposes_stable_request_fields(build_request: RequestFactory) -> None:
    request = build_request(method="POST", path="/users?active=true", raw_body=b'{"name":"Ada"}')
    wrapped = StarletteHttpRequest(request)

    assert wrapped.method == "POST"
    assert wrapped.path == "/users"
    assert wrapped.headers["host"] == "testserver"
    assert wrapped.query_params["active"] == "true"
    assert anyio.run(wrapped.body) == b'{"name":"Ada"}'


def test_no_starlette_object_is_reachable_through_the_request_contract(
    build_request: RequestFactory,
) -> None:
    request: HttpRequest = StarletteHttpRequest(
        build_request(path="/users?active=true&active=false", cookies={"session": "abc"})
    )

    assert isinstance(request.url, Url)
    assert not isinstance(request.url, StarletteURL)
    assert isinstance(request.query_params, QueryParams)
    assert not isinstance(request.query_params, StarletteQueryParams)
    assert isinstance(request.state, RequestState)
    assert not isinstance(request.state, StarletteState)
    assert isinstance(request.headers, Headers)
    assert type(request.path_params) is dict
    assert type(request.cookies) is dict
    assert isinstance(request.slots, RequestSlots)
    assert isinstance(request.client, HttpClientInfo)


def test_the_url_reports_the_parts_the_request_arrived_with(
    build_request: RequestFactory,
) -> None:
    url = StarletteHttpRequest(build_request(path="/users?active=true")).url

    assert url.scheme == "http"
    assert url.host == "testserver"
    assert url.path == "/users"
    assert url.query_string == "active=true"


def test_repeated_query_parameters_keep_every_value(build_request: RequestFactory) -> None:
    query_params = StarletteHttpRequest(build_request(path="/users?tag=a&tag=b")).query_params

    assert query_params.getlist("tag") == ["a", "b"]
    assert query_params["tag"] == "b"


def test_state_written_through_one_wrapper_is_read_through_the_next(
    build_request: RequestFactory,
) -> None:
    request = build_request()

    StarletteHttpRequest(request).state.principal = "ada"

    assert StarletteHttpRequest(request).state.principal == "ada"
    # The Starlette request keeps the same state, because it is the same storage.
    assert request.state.principal == "ada"


def test_the_typed_slots_are_the_same_object_for_the_same_request(
    build_request: RequestFactory,
) -> None:
    request = build_request()

    first = StarletteHttpRequest(request).slots
    second = StarletteHttpRequest(request).slots

    assert first is second
    assert first.rate_limit is None


def test_a_request_with_no_client_reports_none(build_request: RequestFactory) -> None:
    request = build_request()
    del request.scope["client"]

    assert StarletteHttpRequest(request).client is None


def test_wrapping_an_already_wrapped_request_returns_it_unchanged(
    build_request: RequestFactory,
) -> None:
    wrapped = StarletteHttpRequest(build_request())

    assert from_starlette_request(wrapped) is wrapped


def test_wrapping_a_starlette_request_produces_the_neutral_contract(
    build_request: RequestFactory,
) -> None:
    request = build_request()

    converted = from_starlette_request(request)

    assert isinstance(converted, StarletteHttpRequest)
    assert converted.native_request is request


def test_something_that_is_already_neutral_is_passed_through() -> None:
    sentinel = object()

    assert from_starlette_request(sentinel) is sentinel


def test_the_wrapper_decodes_a_json_body(build_request: RequestFactory) -> None:
    request = build_request(method="POST", path="/users", json_body={"name": "Ada"})

    assert anyio.run(StarletteHttpRequest(request).json) == {"name": "Ada"}


@pytest.mark.parametrize("attribute", ["app", "native_request"])
def test_the_declared_escape_hatches_still_reach_the_transport(
    build_request: RequestFactory, build_app: AppFactory, attribute: str
) -> None:
    app = build_app()
    wrapped = StarletteHttpRequest(build_request(app=app))

    assert getattr(wrapped, attribute) is not None
    assert isinstance(wrapped.native_request, Request)


def _chunked(request: Request, body: bytes, *, chunk_bytes: int) -> tuple[Request, list[int]]:
    """Rebuild *request* around a body delivered in chunks, recording what is handed out.

    The shared factory delivers a body in one message, which is what a small request
    looks like. A limit that is enforced while the body is read can only be told apart
    from one enforced after it by a body that arrives in more than one piece, so this
    supplies the receive callable that sends one, and the list of chunk sizes it got to.
    """

    handed_out: list[int] = []
    offset = 0

    async def receive() -> dict[str, object]:
        nonlocal offset
        chunk = body[offset : offset + chunk_bytes]
        offset += len(chunk)
        handed_out.append(len(chunk))
        return {"type": "http.request", "body": chunk, "more_body": offset < len(body)}

    return Request(request.scope, receive), handed_out


def test_a_body_over_the_applications_limit_is_refused_before_the_rest_arrives(
    build_request: RequestFactory, build_app: AppFactory
) -> None:
    app = build_app()
    set_request_limits(app, RequestLimits(max_body_bytes=16))
    request, handed_out = _chunked(
        build_request(method="POST", path="/notes", app=app), b"x" * 4096, chunk_bytes=8
    )

    with pytest.raises(RequestBodyTooLargeError, match="exceeds the 16 byte limit"):
        anyio.run(StarletteHttpRequest(request).body)

    # Three chunks: two inside the limit and the one that crossed it. The remaining
    # 4072 bytes are never asked for.
    assert handed_out == [8, 8, 8]


def test_a_body_within_the_applications_limit_is_read_whole(
    build_request: RequestFactory, build_app: AppFactory
) -> None:
    app = build_app()
    set_request_limits(app, RequestLimits(max_body_bytes=16))
    request, _ = _chunked(
        build_request(method="POST", path="/notes", app=app), b'{"name":"Ada"}', chunk_bytes=4
    )

    assert anyio.run(StarletteHttpRequest(request).body) == b'{"name":"Ada"}'


def test_a_request_with_no_application_behind_it_is_read_under_the_default_limit(
    build_request: RequestFactory,
) -> None:
    # Nothing to ask about limits is not a reason to read without one: an oversized
    # body is refused here exactly as it is for a request an application is serving.
    chunk_bytes = DEFAULT_MAX_BODY_BYTES // 4
    request, handed_out = _chunked(
        build_request(method="POST", path="/notes"),
        b"x" * (DEFAULT_MAX_BODY_BYTES * 2),
        chunk_bytes=chunk_bytes,
    )

    with pytest.raises(RequestBodyTooLargeError):
        anyio.run(StarletteHttpRequest(request).body)

    assert sum(handed_out) <= DEFAULT_MAX_BODY_BYTES + chunk_bytes


def test_a_json_body_is_decoded_from_the_read_the_limit_bounded(
    build_request: RequestFactory, build_app: AppFactory
) -> None:
    app = build_app()
    set_request_limits(app, RequestLimits(max_body_bytes=8))
    request, _ = _chunked(
        build_request(method="POST", path="/notes", json_body={"name": "Ada"}, app=app),
        b'{"name":"Ada"}',
        chunk_bytes=4,
    )

    with pytest.raises(RequestBodyTooLargeError):
        anyio.run(StarletteHttpRequest(request).json)


def test_the_bounded_read_is_the_requests_one_read(
    build_request: RequestFactory, build_app: AppFactory
) -> None:
    # Form parsing and the transport's own request object read the body through
    # Starlette, which asks the client for it once and remembers it. The bounded read
    # has to leave that memory filled, or a second reader either sees nothing or waits
    # for a body the client has already finished sending.
    app = build_app()
    set_request_limits(app, RequestLimits(max_body_bytes=1024))
    request, handed_out = _chunked(
        build_request(
            method="POST",
            path="/notes",
            content_type="application/x-www-form-urlencoded",
            app=app,
        ),
        b"name=Ada&name=Grace",
        chunk_bytes=4,
    )
    wrapped = StarletteHttpRequest(request)

    async def read_twice() -> tuple[bytes, list[object]]:
        body = await wrapped.body()
        form = await wrapped.form()
        return body, form.getlist("name")

    body, names = anyio.run(read_twice)

    assert body == b"name=Ada&name=Grace"
    assert names == ["Ada", "Grace"]
    assert sum(handed_out) == len(b"name=Ada&name=Grace")


UPLOAD_BOUNDARY = "bustanteststarletteboundary"
UPLOAD_MEDIA_TYPE = f"multipart/form-data; boundary={UPLOAD_BOUNDARY}"


def _multipart(payload: bytes) -> bytes:
    """One multipart body carrying *payload* as an uploaded file."""

    head = (
        f"--{UPLOAD_BOUNDARY}\r\n"
        'Content-Disposition: form-data; name="document"; filename="note.txt"\r\n'
        "Content-Type: text/plain\r\n"
        "\r\n"
    ).encode()
    return head + payload + f"\r\n--{UPLOAD_BOUNDARY}--\r\n".encode()


def test_a_form_over_the_applications_upload_limit_is_refused_before_the_rest_arrives(
    build_request: RequestFactory, build_app: AppFactory
) -> None:
    # Left to the transport, a multipart body has no total bound: its parser spools a
    # part past a threshold onto disk, so the whole of a body no route will accept is
    # written into this process before anything looks at the limit.
    app = build_app()
    set_request_limits(app, RequestLimits(max_upload_bytes=64))
    request, handed_out = _chunked(
        build_request(method="POST", path="/uploads", content_type=UPLOAD_MEDIA_TYPE, app=app),
        _multipart(b"x" * 4096),
        chunk_bytes=16,
    )

    with pytest.raises(RequestBodyTooLargeError, match="exceeds the 64 byte limit"):
        anyio.run(StarletteHttpRequest(request).form)

    assert sum(handed_out) <= 64 + 16


def test_an_upload_within_the_applications_limit_is_still_served(
    build_request: RequestFactory, build_app: AppFactory
) -> None:
    app = build_app()
    set_request_limits(app, RequestLimits(max_upload_bytes=1024))
    body = _multipart(b"conformance upload")
    request, handed_out = _chunked(
        build_request(method="POST", path="/uploads", content_type=UPLOAD_MEDIA_TYPE, app=app),
        body,
        chunk_bytes=16,
    )

    async def read_upload() -> tuple[str | None, bytes]:
        form = await StarletteHttpRequest(request).form()
        document = form.get("document")
        assert isinstance(document, StarletteUploadFile)
        return document.filename, await document.read()

    filename, content = anyio.run(read_upload)

    assert filename == "note.txt"
    assert content == b"conformance upload"
    assert sum(handed_out) == len(body)


def test_a_form_is_read_under_the_upload_bound_and_not_the_body_bound(
    build_request: RequestFactory, build_app: AppFactory
) -> None:
    # The two bounds are two figures for two different things, and a route that accepts
    # uploads is expected to carry more than a body that binds ordinary parameters.
    app = build_app()
    set_request_limits(app, RequestLimits(max_body_bytes=16, max_upload_bytes=1024))
    request, _ = _chunked(
        build_request(method="POST", path="/uploads", content_type=UPLOAD_MEDIA_TYPE, app=app),
        _multipart(b"conformance upload"),
        chunk_bytes=16,
    )

    async def read_filename() -> object:
        form = await StarletteHttpRequest(request).form()
        document = form.get("document")
        assert isinstance(document, StarletteUploadFile)
        return document.filename

    assert anyio.run(read_filename) == "note.txt"
