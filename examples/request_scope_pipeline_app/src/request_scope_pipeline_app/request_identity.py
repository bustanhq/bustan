"""Request-local identity state for the pipeline example."""

from typing import Annotated

from bustan import REQUEST, HttpRequest, Inject, Injectable, Scope
from bustan.errors import UnauthorizedException


@Injectable(scope=Scope.REQUEST)
class RequestIdentity:
    def __init__(self, request: Annotated[HttpRequest, Inject(REQUEST)]) -> None:
        self.path = request.url.path
        self.request_id = request.headers.get("x-request-id", "missing")
        self.user_id = request.headers.get("x-user-id")

    def require_user_id(self) -> str:
        user_id = self.user_id
        if user_id is None:
            raise UnauthorizedException("Authenticated request expected")
        return user_id
