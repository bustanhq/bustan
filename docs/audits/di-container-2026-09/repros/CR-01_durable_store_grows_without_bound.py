# ruff: noqa
"""The durable instance store has no eviction policy and no size limit.

The partition key is whatever the provider derives from the request, so an
unauthenticated caller who varies one header allocates one retained instance -
and one retained Request - per distinct value, until the process runs out of
memory.
"""

from __future__ import annotations

from starlette.requests import Request
from starlette.testclient import TestClient

from bustan import Controller, Get, Injectable, Module, Scope, create_app

DISTINCT_TENANTS = 200


@Injectable(scope=Scope.DURABLE)
class Partition:
    @classmethod
    def get_durable_context_key(cls, request: Request | None):
        if request is None:
            return "no-request"
        return request.headers.get("x-tenant", "unknown")

    def __init__(self) -> None:
        self.payload = "x" * 1024


@Controller("/partition", scope=Scope.TRANSIENT)
class PartitionController:
    def __init__(self, partition: Partition) -> None:
        self.partition = partition

    @Get()
    async def read(self) -> dict:
        return {"ok": True}


@Module(controllers=[PartitionController], providers=[Partition])
class AppModule:
    pass


def main() -> None:
    app = create_app(AppModule)
    scope_manager = app.container.scope_manager

    with TestClient(app) as client:
        for index in range(DISTINCT_TENANTS):
            client.get("/partition", headers={"x-tenant": f"tenant-{index}"})

    retained = len(scope_manager.durable_instances)
    print(f"distinct header values sent: {DISTINCT_TENANTS}")
    print(f"durable instances retained:  {retained}")

    if retained >= DISTINCT_TENANTS:
        print(
            "RESULT: CR-01 REPRODUCED - the durable store grew once per distinct "
            f"header value and evicted nothing ({retained} retained)"
        )
    else:
        print(f"RESULT: CR-01 FIXED - the store is bounded ({retained} retained)")


main()
