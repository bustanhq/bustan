# ruff: noqa
"""A durable provider may inject Request and retains it for the life of the partition.

The first caller into a partition supplies the Request the provider keeps. Every
later caller routed to that partition reads the first caller's headers, including
their Authorization header.
"""

from __future__ import annotations

from starlette.requests import Request
from starlette.testclient import TestClient

from bustan import Controller, Get, Injectable, Module, Scope, create_app


@Injectable(scope=Scope.DURABLE)
class TenantSession:
    @classmethod
    def get_durable_context_key(cls, request: Request | None):
        if request is None:
            return "no-request"
        return request.headers.get("x-tenant", "unknown")

    def __init__(self, request: Request) -> None:
        self.retained_request = request
        self.first_user = request.headers.get("x-user", "anonymous")


@Controller("/session")
class SessionController:
    def __init__(self, session: TenantSession) -> None:
        self.session = session

    @Get()
    async def read(self) -> dict:
        return {
            "first_user": self.session.first_user,
            "retained_authorization": self.session.retained_request.headers.get(
                "authorization", ""
            ),
        }


@Module(controllers=[SessionController], providers=[TenantSession])
class AppModule:
    pass


def main() -> None:
    try:
        app = create_app(AppModule)
    except Exception as exc:
        print(f"BOOTSTRAP REJECTED: {type(exc).__name__}: {exc}")
        print("RESULT: RI-04 FIXED - Request injection into a durable provider is refused")
        return

    with TestClient(app) as client:
        alice = client.get(
            "/session",
            headers={"x-tenant": "acme", "x-user": "alice", "authorization": "Bearer alice-token"},
        )
        bob = client.get(
            "/session",
            headers={"x-tenant": "acme", "x-user": "bob", "authorization": "Bearer bob-token"},
        )

    print(f"alice -> {alice.status_code} {alice.text}")
    print(f"bob   -> {bob.status_code} {bob.text}")

    if alice.status_code != 200 or bob.status_code != 200:
        print("RESULT: RI-04 ERROR - a request failed rather than leaking; inspect above")
        return

    body = bob.json()
    if body.get("first_user") == "alice" or "alice-token" in body.get("retained_authorization", ""):
        print("RESULT: RI-04 REPRODUCED - bob read alice's retained request")
    else:
        print("RESULT: RI-04 FIXED - each caller saw only their own request")


main()
