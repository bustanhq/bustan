"""Interceptor that adds request metadata around a handler result."""

from bustan import CallHandler, ExecutionContext, Interceptor, Injectable

from .request_identity import RequestIdentity


@Injectable(scope="request")
class RequestEnvelopeInterceptor(Interceptor):
    def __init__(self, request_identity: RequestIdentity) -> None:
        self.request_identity = request_identity

    async def intercept(self, context: ExecutionContext, next: CallHandler) -> object:
        result = await next.handle()
        return {
            "request_id": self.request_identity.request_id,
            "user_id": self.request_identity.user_id,
            "data": result,
        }