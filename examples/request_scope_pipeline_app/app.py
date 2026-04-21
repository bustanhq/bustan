"""Example showing one request-scoped provider shared across the pipeline."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from bustan import (
    Guard,
    Interceptor,
    Controller,
    create_app,
    Get,
    Injectable,
    Module,
    UseGuards,
    UseInterceptors,
)
from bustan.pipeline.context import HandlerContext, RequestContext
from typing import Any, cast
from starlette.requests import Request
from starlette.testclient import TestClient


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


@Injectable
class ProfileService:
    def read_profile(self, user_id: str) -> dict[str, str]:
        return {
            "user_id": user_id,
            "plan": "pro",
        }


@Injectable(scope="request")
class AuthenticatedGuard(Guard):
    def __init__(self, request_identity: RequestIdentity) -> None:
        self.request_identity = request_identity

    async def can_activate(self, context: RequestContext) -> bool:
        return self.request_identity.user_id is not None


@Injectable(scope="request")
class RequestEnvelopeInterceptor(Interceptor):
    def __init__(self, request_identity: RequestIdentity) -> None:
        self.request_identity = request_identity

    async def intercept(
        self,
        context: HandlerContext,
        call_next: Callable[[], Awaitable[object]],
    ) -> object:
        result = await call_next()
        return {
            "request_id": self.request_identity.request_id,
            "user_id": self.request_identity.user_id,
            "data": result,
        }


@UseGuards(AuthenticatedGuard)
@UseInterceptors(RequestEnvelopeInterceptor)
@Controller("/account")
class AccountController:
    def __init__(
        self,
        profile_service: ProfileService,
        request_identity: RequestIdentity,
    ) -> None:
        self.profile_service = profile_service
        self.request_identity = request_identity

    @Get("/me")
    def read_current_account(self) -> dict[str, str]:
        user_id = self.request_identity.require_user_id()
        profile = self.profile_service.read_profile(user_id)
        return {
            "path": self.request_identity.path,
            **profile,
        }


@Module(
    controllers=[AccountController],
    providers=[
        ProfileService,
        RequestIdentity,
        AuthenticatedGuard,
        RequestEnvelopeInterceptor,
    ],
    exports=[ProfileService],
)
class AppModule:
    pass


app = create_app(AppModule)


def demo_pipeline() -> None:
    """Show the rejected and accepted paths for the request-scoped pipeline."""

    with TestClient(cast(Any, app)) as client:
        # The first request omits authentication headers, so the guard rejects it.
        print(client.get("/account/me").status_code)
        print(
            # The second request exercises the full guard -> interceptor -> controller flow.
            client.get(
                "/account/me",
                headers={
                    "x-user-id": "moses",
                    "x-request-id": "req-42",
                },
            ).json()
        )


if __name__ == "__main__":
    demo_pipeline()
