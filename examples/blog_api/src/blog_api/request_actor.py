"""Request-local actor context for the blog API example."""

from typing import Annotated

from bustan import REQUEST, HttpRequest, Inject, Injectable, Scope


@Injectable(scope=Scope.REQUEST)
class RequestActor:
    def __init__(self, request: Annotated[HttpRequest, Inject(REQUEST)]) -> None:
        self.user_id = request.headers.get("x-user-id", "anonymous")
