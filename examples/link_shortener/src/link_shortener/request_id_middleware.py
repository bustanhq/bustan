"""Work that happens on every request a route handles, after routing has chosen the route."""

from __future__ import annotations

from uuid import uuid4

from bustan import HttpRequest, Middleware


class RequestIdMiddleware(Middleware):
    """Stamps an id on every request it wraps and echoes it on the response.

    Middleware is the first stage of a route's pipeline. It runs once routing has chosen
    the route, so a request answered before one is chosen, such as a path no route serves,
    is never stamped. It is handed the request and nothing naming the handler or what its
    route declares, which is why identity checks belong in a guard instead. This only
    needs to run early and on every route, so it belongs here.
    """

    async def use(self, request: HttpRequest, call_next: object) -> object:
        request_id = request.headers.get("x-request-id") or str(uuid4())
        response = await call_next(request)  # type: ignore[operator]
        response.headers["x-request-id"] = request_id
        return response
