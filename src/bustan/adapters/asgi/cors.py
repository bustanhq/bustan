"""This transport's own CORS enforcement, written against ASGI and the standard library.

An application served without a web framework still has to answer a browser's preflight
request, and still has to say which origins may read its responses, so this adapter
carries its own implementation of the protocol rather than borrowing one from a library
it deliberately does not depend on.

What it implements is the cross-origin protocol as browsers enforce it, which is also
what the Starlette adapter's middleware implements, so the two adapters answer a
cross-origin request identically and an application that changes transport does not
change what a browser sees.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...contracts import Headers
from ...contracts.cors import CorsOptions, allowed_origins
from .responses import AsgiResponse

if TYPE_CHECKING:
    from .types import AsgiApp, Message, Receive, Scope, Send

# What a policy naming ``*`` as its methods is read as. A preflight answer has to name
# the methods it allows, and ``*`` on its own names none of them.
ALL_METHODS = ("DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT")

# Headers a browser is allowed to send without asking permission first, so a policy
# allows them whether or not it listed them. Refusing one would refuse requests that no
# policy meant to refuse.
SAFELISTED_HEADERS = frozenset({"Accept", "Accept-Language", "Content-Language", "Content-Type"})


class AsgiCorsMiddleware:
    """Answer preflight requests and mark responses under one cross-origin policy.

    A request carrying no ``origin`` is not a cross-origin request and is served
    untouched. A preflight - ``OPTIONS`` carrying ``access-control-request-method`` - is
    answered here and never reaches a route, because it asks about the policy rather than
    about the resource. Everything else is served as it would have been, with the
    policy's headers written onto the response on its way out.
    """

    __slots__ = (
        "_allow_all_headers",
        "_allow_all_origins",
        "_app",
        "_declared_request_headers",
        "_methods",
        "_named_origins",
        "_options",
        "_permitted_request_headers",
        "_preflight_headers",
        "_simple_headers",
    )

    def __init__(self, app: AsgiApp, options: CorsOptions) -> None:
        # The policy is required rather than defaulted: a middleware built without one
        # would either permit every origin or permit none, and both are a cross-origin
        # decision taken by whoever left the argument out.
        origins = allowed_origins(options)
        self._app = app
        self._options = options
        self._named_origins = frozenset(origins)
        self._allow_all_origins = "*" in origins
        self._allow_all_headers = "*" in options.allowed_headers
        self._methods = ALL_METHODS if "*" in options.methods else tuple(options.methods)
        self._declared_request_headers = sorted(SAFELISTED_HEADERS | set(options.allowed_headers))
        self._permitted_request_headers = {name.lower() for name in self._declared_request_headers}
        self._simple_headers = self._build_simple_headers()
        self._preflight_headers = self._build_preflight_headers()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Serve one connection under the policy this was built with."""

        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return

        headers = _request_headers(scope)
        origin = headers.get("origin")
        if origin is None:
            await self._app(scope, receive, send)
            return

        if scope.get("method") == "OPTIONS" and "access-control-request-method" in headers:
            await self._preflight_answer(headers)(send)
            return

        await self._app(scope, receive, _marking(send, self._served_headers(origin)))

    def allows_origin(self, origin: str) -> bool:
        """Whether a response to a request from *origin* may be read by it."""

        return self._allow_all_origins or origin in self._named_origins

    def _names_the_origin_back(self) -> bool:
        """Whether an answer echoes the origin that asked instead of allowing every one.

        A browser refuses ``*`` on a request that carries credentials, and an answer that
        differs by origin has to say so or a shared cache will hand one origin's answer to
        the next. Either condition means the origin is named rather than starred.
        """

        return not self._allow_all_origins or self._options.credentials

    def _build_simple_headers(self) -> dict[str, str]:
        """The policy headers a served response carries whatever origin asked for it."""

        headers: dict[str, str] = {}
        if self._allow_all_origins:
            headers["access-control-allow-origin"] = "*"
        if self._options.credentials:
            headers["access-control-allow-credentials"] = "true"
        if self._options.exposed_headers:
            headers["access-control-expose-headers"] = ", ".join(self._options.exposed_headers)
        return headers

    def _build_preflight_headers(self) -> dict[str, str]:
        """The policy headers a preflight answer carries before the request is read."""

        headers: dict[str, str] = {}
        if self._names_the_origin_back():
            headers["vary"] = "Origin"
        else:
            headers["access-control-allow-origin"] = "*"
        headers["access-control-allow-methods"] = ", ".join(self._methods)
        headers["access-control-max-age"] = str(self._options.max_age)
        if not self._allow_all_headers:
            headers["access-control-allow-headers"] = ", ".join(self._declared_request_headers)
        if self._options.credentials:
            headers["access-control-allow-credentials"] = "true"
        return headers

    def _served_headers(self, origin: str) -> dict[str, str]:
        """The policy headers one served response carries, given the origin that asked."""

        headers = dict(self._simple_headers)
        if self._names_the_origin_back() and self.allows_origin(origin):
            headers["access-control-allow-origin"] = origin
            headers["vary"] = "Origin"
        return headers

    def _preflight_answer(self, headers: Headers) -> AsgiResponse:
        """Answer one preflight request, naming whatever about it the policy refused.

        A refusal is answered rather than raised, and it says what failed. The browser
        enforces the policy either way, so the only reader of this body is whoever is
        working out why their request never left it.
        """

        answer = dict(self._preflight_headers)
        refused = self._refusals(headers, answer)
        if refused:
            return AsgiResponse(
                status_code=400,
                headers=answer,
                body=("Disallowed CORS " + ", ".join(refused)).encode("utf-8"),
                media_type="text/plain",
            )
        return AsgiResponse(headers=answer, body=b"OK", media_type="text/plain")

    def _refusals(self, headers: Headers, answer: dict[str, str]) -> list[str]:
        """Return what the policy refuses about one preflight, filling in what it allows."""

        refused: list[str] = []
        origin = headers["origin"]
        if not self.allows_origin(origin):
            refused.append("origin")
        elif self._names_the_origin_back():
            answer["access-control-allow-origin"] = origin

        if headers["access-control-request-method"] not in self._methods:
            refused.append("method")

        requested = headers.get("access-control-request-headers")
        if requested is not None and self._allow_all_headers:
            answer["access-control-allow-headers"] = requested
        elif requested is not None and not self._allows_every_requested_header(requested):
            refused.append("headers")

        if "access-control-request-private-network" in headers:
            # No option declares a private network reachable, so the answer is always no.
            # Saying so is what stops a browser treating silence as permission.
            refused.append("private-network")
        return refused

    def _allows_every_requested_header(self, requested: str) -> bool:
        """Whether every header a preflight asked to send is one the policy allows."""

        return all(
            name.strip().lower() in self._permitted_request_headers for name in requested.split(",")
        )


def _request_headers(scope: Scope) -> Headers:
    """Read one request's headers out of the connection scope."""

    raw: list[tuple[bytes, bytes]] = scope.get("headers", [])
    return Headers((name.decode("latin-1"), value.decode("latin-1")) for name, value in raw)


def _marking(send: Send, policy: dict[str, str]) -> Send:
    """Return *send* with the policy's headers written onto the response as it starts."""

    async def send_marked(message: Message) -> None:
        if message.get("type") != "http.response.start":
            await send(message)
            return
        await send({**message, "headers": _merged(message.get("headers", []), policy)})

    return send_marked


def _merged(
    written: list[tuple[bytes, bytes]], policy: dict[str, str]
) -> list[tuple[bytes, bytes]]:
    """Return a response's headers with the policy's own written over them.

    A policy header replaces one the application wrote rather than joining it, because
    two ``access-control-allow-origin`` values are read by a browser as no valid one at
    all. ``vary`` is the exception: it is a list, and whatever the application was
    varying on has to survive alongside ``Origin`` or a cache stops varying on it.
    """

    replaced = {name.encode("latin-1") for name in policy}
    kept = [(name, value) for name, value in written if name.lower() not in replaced]
    varied = [value.decode("latin-1") for name, value in written if name.lower() == b"vary"]
    marked = [
        (
            name.encode("latin-1"),
            ", ".join([*varied, value]).encode("latin-1")
            if name == "vary" and varied
            else value.encode("latin-1"),
        )
        for name, value in policy.items()
    ]
    return [*kept, *marked]


__all__ = (
    "ALL_METHODS",
    "SAFELISTED_HEADERS",
    "AsgiCorsMiddleware",
)
