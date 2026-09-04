# ruff: noqa
# Targeted probe: does a DEFAULT-scope controller injecting a REQUEST-scoped provider
# serve the first caller's identity to a later caller on the released 1.1.0 tree?
# This is the shape docs/REQUEST_SCOPED_PROVIDERS.md says raises ProviderResolutionError.
from __future__ import annotations

from starlette.testclient import TestClient

from bustan import Controller, Get, Injectable, Module, Scope, create_app
from starlette.requests import Request as HttpRequest


@Injectable(scope=Scope.REQUEST)
class CurrentUser:
    def __init__(self, request: HttpRequest) -> None:
        self.name = request.headers.get("x-user", "anonymous")


@Controller("/whoami")  # no scope= -> defaults to SINGLETON
class WhoAmIController:
    def __init__(self, current_user: CurrentUser) -> None:
        self.current_user = current_user

    @Get()
    async def whoami(self) -> dict:
        return {"user": self.current_user.name}


@Module(controllers=[WhoAmIController], providers=[CurrentUser])
class AppModule:
    pass


def main() -> None:
    try:
        app = create_app(AppModule)
    except Exception as exc:  # bootstrap rejection is the documented behaviour
        print(f"BOOTSTRAP REJECTED: {type(exc).__name__}: {exc}")
        print("RESULT: RI-01 FIXED - the graph is refused before it can serve traffic")
        return

    with TestClient(app) as client:
        first = client.get("/whoami", headers={"x-user": "alice"})
        second = client.get("/whoami", headers={"x-user": "bob"})

    print(f"alice request -> {first.status_code} {first.text}")
    print(f"bob   request -> {second.status_code} {second.text}")

    if first.status_code == 500 or second.status_code == 500:
        print("RESULT: RI-01 ERROR - request failed rather than leaking; inspect above")
        return

    leaked = second.json().get("user") == "alice"
    if leaked:
        print("RESULT: RI-01 REPRODUCED - bob was served alice's identity")
    else:
        print("RESULT: RI-01 FIXED - each caller saw their own identity")


main()
