# ruff: noqa
# Evidence script for finding RI-01 (workflow id F-01) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-01: singleton (default-scope) controller injecting request-scoped provider + Request + Response."""
from typing import Any, cast
from starlette.requests import Request
from starlette.responses import Response
from starlette.testclient import TestClient
from bustan import Controller, Get, Injectable, Module, create_app
from bustan.kernel.errors import ProviderResolutionError


@Injectable(scope="request")
class RequestIdentity:
    def __init__(self, request: Request) -> None:
        self.user_id = request.headers.get("x-user-id", "anonymous")


@Controller("/account")  # default scope: SINGLETON
class AccountController:
    def __init__(self, identity: RequestIdentity, request: Request, response: Response) -> None:
        self.identity = identity
        self.request = request
        self.response = response

    @Get("/")
    def me(self) -> dict[str, Any]:
        return {
            "identity_user": self.identity.user_id,
            "request_header_user": self.request.headers.get("x-user-id"),
            "request_id": id(self.request),
            "response_id": id(self.response),
        }


@Module(controllers=[AccountController], providers=[RequestIdentity])
class AppModule:
    pass


leak = False
try:
    with TestClient(cast(Any, create_app(AppModule))) as client:
        a = client.get("/account", headers={"x-user-id": "alice"})
        b = client.get("/account", headers={"x-user-id": "bob"})
        print("alice ->", a.status_code, a.json())
        print("bob   ->", b.status_code, b.json())
        if a.status_code == 200 and b.status_code == 200:
            ja, jb = a.json(), b.json()
            leak = (
                jb["identity_user"] == "alice"
                and jb["request_header_user"] == "alice"
                and jb["request_id"] == ja["request_id"]
                and jb["response_id"] == ja["response_id"]
            )
except ProviderResolutionError as exc:
    print("ProviderResolutionError raised (documented behavior):", exc)

print("LEAK" if leak else "NO LEAK", "- singleton controller served alice identity/Request/Response to bob:", leak)
print("F-01", "CONFIRMED" if leak else "REFUTED")
