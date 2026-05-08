"""Guard that requires a request-scoped user id."""

from bustan import ExecutionContext, Guard, Injectable

from .request_identity import RequestIdentity


@Injectable(scope="request")
class AuthenticatedGuard(Guard):
    def __init__(self, request_identity: RequestIdentity) -> None:
        self.request_identity = request_identity

    async def can_activate(self, context: ExecutionContext) -> bool:
        return self.request_identity.user_id is not None