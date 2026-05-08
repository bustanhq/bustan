"""Request-local identity state for the pipeline example."""

from starlette.requests import Request

from bustan import Injectable


@Injectable(scope="request")
class RequestIdentity:
    def __init__(self, request: Request) -> None:
        self.path = request.url.path
        self.request_id = request.headers.get("x-request-id", "missing")
        self.user_id = request.headers.get("x-user-id")

    def require_user_id(self) -> str:
        user_id = self.user_id
        if user_id is None:
            raise RuntimeError("Authenticated request expected")
        return user_id