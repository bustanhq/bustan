"""Request-local actor context for the blog API example."""

from starlette.requests import Request

from bustan import Injectable


@Injectable(scope="request")
class RequestActor:
    def __init__(self, request: Request) -> None:
        self.user_id = request.headers.get("x-user-id", "anonymous")