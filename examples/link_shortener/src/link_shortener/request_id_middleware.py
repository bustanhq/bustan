"""Work that happens on every request, before routing has chosen anything."""

from __future__ import annotations

from uuid import uuid4

from bustan import HttpRequest, Middleware


class RequestIdMiddleware(Middleware):
    """Stamps an id on every request and echoes it on the response.

    Middleware is the first stage of the pipeline: it sees the raw request and knows
    nothing about which handler will run, which is why identity checks belong in a guard
    instead. This only needs to run early and for everything, so it belongs here.
    """

    async def use(self, request: HttpRequest, call_next: object) -> object:
        request_id = request.headers.get("x-request-id") or str(uuid4())
        response = await call_next(request)  # type: ignore[operator]
        response.headers["x-request-id"] = request_id
        return response
