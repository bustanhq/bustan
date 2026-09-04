# ruff: noqa
"""Per-key durable construction locks are created and never released.

`get_durable_lock` inserts a lock per partition key with `setdefault` and nothing
ever removes it, so the lock table grows in lockstep with the instance store. The
lock outlives the construction it guards, which is the only thing it is for.
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
        self.value = 1


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

    locks = len(scope_manager.durable_locks)
    print(f"distinct header values sent: {DISTINCT_TENANTS}")
    print(f"durable locks retained:      {locks}")

    if locks >= DISTINCT_TENANTS:
        print(
            "RESULT: CR-06 REPRODUCED - one lock retained per partition key after "
            f"construction finished ({locks} retained)"
        )
    else:
        print(f"RESULT: CR-06 FIXED - locks are released after construction ({locks} retained)")


main()
