# ruff: noqa
# Evidence script for finding CR-01 (workflow id F-07) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-07: durable instance and lock caches grow without bound under client-controlled keys.

Durable TenantContext keyed on the x-tenant-id header, consumed by a request-scoped
controller. N requests with distinct header values. Measures:
  - len(scope_manager.durable_instances), len(durable_locks), len(async_construction_locks)
  - tracemalloc growth attributable to the requests
  - whether ScopeManager / Container expose any eviction API for durable entries
  - whether lifecycle shutdown clears the durable caches
Usage: uv run python F-07.py [N] (default 2000)
"""

from __future__ import annotations

import sys
import tracemalloc

from starlette.requests import Request
from starlette.testclient import TestClient

from bustan import Controller, Get, Injectable, Module, Scope, create_app
from bustan.core.ioc.container import Container
from bustan.core.ioc.scopes import ScopeManager


def build_app():
    @Injectable(scope=Scope.DURABLE)
    class TenantContext:
        def __init__(self, request: Request) -> None:
            self.tenant = request.headers.get("x-tenant-id", "none")
            # modest per-tenant payload to make growth visible
            self.payload = bytearray(4096)

        @classmethod
        def get_durable_context_key(cls, request: Request | None) -> str:
            assert request is not None
            return request.headers.get("x-tenant-id", "none")

    @Controller("/t", scope=Scope.REQUEST)
    class TenantController:
        def __init__(self, ctx: TenantContext) -> None:
            self.ctx = ctx

        @Get("/")
        def read(self) -> dict:
            return {"tenant": self.ctx.tenant}

    @Module(controllers=[TenantController], providers=[TenantContext])
    class AppModule:
        pass

    return create_app(AppModule)


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
    app = build_app()
    sm = app.container.scope_manager

    with TestClient(app) as client:
        r = client.get("/t/", headers={"x-tenant-id": "warmup"})
        assert r.status_code == 200, r.text
        base_inst = len(sm.durable_instances)
        base_locks = len(sm.durable_locks)
        base_async = len(sm.async_construction_locks)
        tracemalloc.start()
        snap0 = tracemalloc.take_snapshot()
        for i in range(n):
            r = client.get("/t/", headers={"x-tenant-id": f"attacker-{i}"})
            assert r.status_code == 200, r.text
        snap1 = tracemalloc.take_snapshot()
        cur, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        inst = len(sm.durable_instances) - base_inst
        locks = len(sm.durable_locks) - base_locks
        alocks = len(sm.async_construction_locks) - base_async
        diff = sum(s.size_diff for s in snap1.compare_to(snap0, "filename"))
        print(f"requests={n} durable_instances(+)={inst} durable_locks(+)={locks} async_construction_locks(+)={alocks}")
        print(f"traced memory growth ~{diff / 1e6:.2f} MB (current={cur / 1e6:.2f} MB, peak={peak / 1e6:.2f} MB)")

        # Same key again: no further growth (cache hit), proves key is the header
        r = client.get("/t/", headers={"x-tenant-id": "attacker-0"})
        print(f"repeat key: durable_instances(+)={len(sm.durable_instances) - base_inst} (unchanged => keyed on header)")

    # after lifespan shutdown
    print(f"after lifespan shutdown: durable_instances={len(sm.durable_instances)} durable_locks={len(sm.durable_locks)}")

    # eviction API survey
    sm_api = sorted(a for a in dir(ScopeManager) if not a.startswith("_"))
    c_api = sorted(a for a in dir(Container) if not a.startswith("_"))
    durable_evict = [a for a in sm_api + c_api if "durable" in a.lower() and ("clear" in a.lower() or "evict" in a.lower() or "remove" in a.lower() or "del" in a.lower())]
    clearing = [a for a in sm_api if a.startswith(("clear", "evict", "remove", "reset", "pop"))]
    print(f"ScopeManager clearing methods: {clearing}")
    print(f"durable eviction methods on ScopeManager/Container: {durable_evict}")

    grew_linearly = inst == n and locks == n
    no_api = not durable_evict
    if grew_linearly and no_api:
        print("RESULT: CONFIRMED - one instance + one lock per distinct client-supplied key, never evicted, no eviction API")
    else:
        print("RESULT: NOT CONFIRMED as described")


if __name__ == "__main__":
    main()
