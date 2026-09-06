"""An in-process client that drives an ASGI application without a socket.

A conformance suite asks each adapter for the client its own users would drive, so this
is that client for raw ASGI: it builds a connection scope, calls the application, and
collects the messages it writes back. Nothing is listening on a port and no HTTP is
parsed, because the application is called directly.
"""

from __future__ import annotations

import asyncio
import json as json_module
import threading
from http.cookies import SimpleCookie
from typing import TYPE_CHECKING, cast
from urllib.parse import urlencode, urlsplit

from ...contracts import Headers
from .lifespan import LifespanRunner

if TYPE_CHECKING:
    from collections.abc import Coroutine, Iterable, Mapping
    from typing import Any

    from .types import AsgiApp, Message, Scope

# What a client that never asked to be anything else calls itself, and where it says it
# is calling from; a handler reading the Host header sees this.
DEFAULT_BASE_URL = "http://testserver"
DEFAULT_USER_AGENT = "bustan-asgi-testclient"

# Statuses whose Location header this client follows, and the two that turn the followed
# request into a GET the way every browser and HTTP client does.
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_REDIRECT_TO_GET = frozenset({301, 302, 303})
_MAX_REDIRECTS = 20


class AsgiTestResponse:
    """What one request to the application produced.

    ``status_code`` is the status the application started its response with,
    ``headers`` the headers it sent, ``content`` the body as raw bytes, and ``url``
    the target the request finally landed on, which differs from the one asked for
    when redirects were followed.
    """

    __slots__ = ("content", "headers", "status_code", "url")

    def __init__(self, status_code: int, headers: Headers, content: bytes, url: str) -> None:
        self.status_code = status_code
        self.headers = headers
        self.content = content
        self.url = url

    @property
    def text(self) -> str:
        """The body decoded as UTF-8."""

        return self.content.decode("utf-8")

    def json(self) -> Any:
        """The body decoded as JSON."""

        return json_module.loads(self.content)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(status_code={self.status_code}, url={self.url!r})"


class AsgiTestClient:
    """Drives one ASGI application in process, one request at a time.

    Used as a context manager it runs the application's lifespan, so startup has
    finished before the first request and shutdown runs after the last; used without
    one, it sends requests to an application that was never started, which is what a
    test that does not care about the lifespan wants.

    Cookies a response set are kept and sent with later requests, so a test that logs in
    and then asks for something stays logged in.
    """

    def __init__(self, app: AsgiApp, *, base_url: str = DEFAULT_BASE_URL) -> None:
        self._app = app
        self._base_url = base_url.rstrip("/")
        self.cookies: dict[str, str] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._lifespan: LifespanRunner | None = None

    def __enter__(self) -> AsgiTestClient:
        """Start the application, on a loop that lives until the block ends.

        The lifespan and every request in the block run on one event loop, in one thread,
        so anything startup created is still usable by the requests that follow it.
        """

        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, daemon=True, name="bustan-asgi-client")
        thread.start()
        self._loop, self._thread = loop, thread
        self._lifespan = LifespanRunner(self._app)
        try:
            self._run(self._lifespan.startup())
        except BaseException:
            self._stop_loop()
            raise
        return self

    def __exit__(self, *exception: object) -> None:
        """Stop the application and release the loop it ran on."""

        try:
            if self._lifespan is not None:
                self._run(self._lifespan.shutdown())
        finally:
            self._lifespan = None
            self._stop_loop()

    def get(self, url: str, **options: Any) -> AsgiTestResponse:
        """Send a GET request."""

        return self.request("GET", url, **options)

    def head(self, url: str, **options: Any) -> AsgiTestResponse:
        """Send a HEAD request."""

        return self.request("HEAD", url, **options)

    def options(self, url: str, **options: Any) -> AsgiTestResponse:
        """Send an OPTIONS request."""

        return self.request("OPTIONS", url, **options)

    def post(self, url: str, **options: Any) -> AsgiTestResponse:
        """Send a POST request."""

        return self.request("POST", url, **options)

    def put(self, url: str, **options: Any) -> AsgiTestResponse:
        """Send a PUT request."""

        return self.request("PUT", url, **options)

    def patch(self, url: str, **options: Any) -> AsgiTestResponse:
        """Send a PATCH request."""

        return self.request("PATCH", url, **options)

    def delete(self, url: str, **options: Any) -> AsgiTestResponse:
        """Send a DELETE request."""

        return self.request("DELETE", url, **options)

    def request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        content: bytes | str | None = None,
        data: Mapping[str, str] | None = None,
        json: object | None = None,
        cookies: Mapping[str, str] | None = None,
        follow_redirects: bool = True,
    ) -> AsgiTestResponse:
        """Send one request and return what the application answered.

        The body is whichever of ``content``, ``data`` and ``json`` was supplied; the
        last two also set the content type the application will parse them with.
        """

        body, body_headers = _encode_body(content, data, json)
        request_headers = {**body_headers, **dict(headers or {})}
        target = _target(url, params)
        response = self._run(self._call(method.upper(), target, request_headers, body, cookies))
        redirects = 0
        while follow_redirects and response.status_code in _REDIRECT_STATUSES:
            redirects += 1
            if redirects > _MAX_REDIRECTS:
                raise RuntimeError(f"Exceeded {_MAX_REDIRECTS} redirects for {target}")
            if response.status_code in _REDIRECT_TO_GET:
                method, body, request_headers = "GET", b"", dict(headers or {})
            target = response.headers["location"]
            response = self._run(self._call(method, target, request_headers, body, cookies))
        return response

    async def _call(
        self,
        method: str,
        target: str,
        headers: Mapping[str, str],
        body: bytes,
        cookies: Mapping[str, str] | None,
    ) -> AsgiTestResponse:
        scope = self._build_scope(method, target, headers, body, cookies)
        messages: list[Message] = []

        async def send(message: Message) -> None:
            messages.append(message)

        await self._app(scope, _body_stream(body), send)
        return self._read_response(messages, target)

    def _build_scope(
        self,
        method: str,
        target: str,
        headers: Mapping[str, str],
        body: bytes,
        cookies: Mapping[str, str] | None,
    ) -> Scope:
        split = urlsplit(target if "://" in target else f"{self._base_url}{target}")
        sent = {
            "host": split.netloc,
            "user-agent": DEFAULT_USER_AGENT,
            "accept": "*/*",
            "connection": "close",
            **{name.lower(): value for name, value in headers.items()},
        }
        jar = {**self.cookies, **dict(cookies or {})}
        if jar:
            sent["cookie"] = "; ".join(f"{name}={value}" for name, value in jar.items())
        if body and "content-length" not in sent:
            sent["content-length"] = str(len(body))
        return {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": method,
            "scheme": split.scheme or "http",
            "path": split.path or "/",
            "raw_path": (split.path or "/").encode("latin-1"),
            "query_string": split.query.encode("latin-1"),
            "root_path": "",
            "headers": [
                (name.encode("latin-1"), value.encode("latin-1")) for name, value in sent.items()
            ],
            "client": ("testclient", 50000),
            "server": (split.hostname or "testserver", split.port),
        }

    def _read_response(self, messages: Iterable[Message], url: str) -> AsgiTestResponse:
        status = 500
        headers = Headers()
        chunks: list[bytes] = []
        for message in messages:
            if message.get("type") == "http.response.start":
                status = cast(int, message["status"])
                headers = Headers(
                    (name.decode("latin-1"), value.decode("latin-1"))
                    for name, value in cast("list[tuple[bytes, bytes]]", message["headers"])
                )
            elif message.get("type") == "http.response.body":
                chunks.append(cast(bytes, message.get("body", b"")))
        self._store_cookies(headers)
        return AsgiTestResponse(status, headers, b"".join(chunks), url)

    def _store_cookies(self, headers: Headers) -> None:
        for header in headers.getlist("set-cookie"):
            jar: SimpleCookie = SimpleCookie()
            jar.load(header)
            for name, morsel in jar.items():
                if morsel.value:
                    self.cookies[name] = morsel.value
                else:
                    self.cookies.pop(name, None)

    def _run(self, coroutine: Coroutine[Any, Any, Any]) -> Any:
        loop = self._loop
        if loop is None:
            return asyncio.run(coroutine)
        return asyncio.run_coroutine_threadsafe(coroutine, loop).result()

    def _stop_loop(self) -> None:
        loop, thread = self._loop, self._thread
        self._loop, self._thread = None, None
        if loop is not None and thread is not None:
            loop.call_soon_threadsafe(loop.stop)
            thread.join()
            loop.close()


def _target(url: str, params: Mapping[str, str] | None) -> str:
    if not params:
        return url
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{urlencode(params)}"


def _encode_body(
    content: bytes | str | None,
    data: Mapping[str, str] | None,
    json: object | None,
) -> tuple[bytes, dict[str, str]]:
    if json is not None:
        return json_module.dumps(json).encode("utf-8"), {"content-type": "application/json"}
    if data is not None:
        return (
            urlencode(data).encode("utf-8"),
            {"content-type": "application/x-www-form-urlencoded"},
        )
    if content is None:
        return b"", {}
    return (content.encode("utf-8") if isinstance(content, str) else content), {}


def _body_stream(body: bytes):
    """Return a receive callable that yields *body* once, then a disconnect."""

    messages = [
        {"type": "http.request", "body": body, "more_body": False},
        {"type": "http.disconnect"},
    ]

    async def receive() -> Message:
        return messages.pop(0) if len(messages) > 1 else messages[0]

    return receive


__all__ = (
    "DEFAULT_BASE_URL",
    "AsgiTestClient",
    "AsgiTestResponse",
)
