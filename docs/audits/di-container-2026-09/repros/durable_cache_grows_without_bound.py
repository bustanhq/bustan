"""CR-01: durable instances and their locks are keyed by whatever get_durable_context_key returns
and are never evicted. When the key derives from a request header, an unauthenticated client can
grow process memory without bound (one instance plus one threading.Lock per distinct value).
"""

from starlette.requests import Request
from starlette.testclient import TestClient

from bustan import Controller, Get, Injectable, Module, Scope, create_app

REQUESTS = 2000


@Injectable(scope=Scope.DURABLE)
class TenantContext:
    def __init__(self) -> None:
        self.payload = bytearray(1024)

    @classmethod
    def get_durable_context_key(cls, request: Request | None) -> str:
        return request.headers.get("x-tenant", "none") if request is not None else "none"


@Controller("/t", scope=Scope.REQUEST)
class TenantController:
    def __init__(self, ctx: TenantContext, request: Request) -> None:
        self.ctx = ctx
        self.request = request

    @Get("/")
    def get(self) -> dict[str, str]:
        return {"tenant": self.request.headers.get("x-tenant", "none")}


@Module(controllers=[TenantController], providers=[TenantContext])
class AppModule:
    pass


def main() -> None:
    app = create_app(AppModule)
    scope_manager = app.container.scope_manager
    with TestClient(app) as client:
        for index in range(REQUESTS):
            client.get("/t/", headers={"x-tenant": f"tenant-{index}"})
    instances = len(scope_manager.durable_instances)
    locks = len(scope_manager.construction_locks)
    if instances >= REQUESTS:
        print(
            f"RESULT: CR-01 REPRODUCED - {instances} durable instances and {locks} locks retained"
        )
    else:
        print(f"RESULT: CR-01 FIXED - {instances} durable instances retained after {REQUESTS} keys")


if __name__ == "__main__":
    main()
