# ruff: noqa
"""A durable-scoped controller falls through to the singleton path.

`@Controller(scope=Scope.DURABLE)` is accepted by the decorator, but the
controller factory handles only TRANSIENT and REQUEST explicitly and treats
everything else as a process-wide singleton. One instance is therefore built once
and shared across every tenant partition it was supposed to separate.
"""

from __future__ import annotations

from starlette.requests import Request
from starlette.testclient import TestClient

from bustan import Controller, Get, Module, Scope, create_app


@Controller("/tenant", scope=Scope.DURABLE)
class TenantController:
    instances = 0

    @classmethod
    def get_durable_context_key(cls, request: Request | None):
        if request is None:
            return "no-request"
        return request.headers.get("x-tenant", "unknown")

    def __init__(self) -> None:
        TenantController.instances += 1
        self.instance_number = TenantController.instances

    @Get()
    async def read(self) -> dict:
        return {"instance": self.instance_number}


@Module(controllers=[TenantController])
class AppModule:
    pass


def main() -> None:
    try:
        app = create_app(AppModule)
    except Exception as exc:
        print(f"BOOTSTRAP REJECTED: {type(exc).__name__}: {exc}")
        print("RESULT: RI-10 FIXED - a durable-scoped controller is refused explicitly")
        return

    with TestClient(app) as client:
        a = client.get("/tenant", headers={"x-tenant": "acme"})
        b = client.get("/tenant", headers={"x-tenant": "globex"})

    print(f"tenant acme   -> {a.status_code} {a.text}")
    print(f"tenant globex -> {b.status_code} {b.text}")
    print(f"controllers constructed: {TenantController.instances}")

    if a.status_code != 200 or b.status_code != 200:
        print("RESULT: RI-10 ERROR - a request failed; inspect above")
        return

    if a.json().get("instance") == b.json().get("instance"):
        print("RESULT: RI-10 REPRODUCED - two tenants shared one durable controller instance")
    else:
        print("RESULT: RI-10 FIXED - each tenant partition got its own instance")


main()
