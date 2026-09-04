# ruff: noqa
# Evidence script for finding OL-12 (workflow id F-49) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-49: durable instances are excluded from eager warmup and from every lifecycle stage.

Scenario: TenantPool (Scope.DURABLE) implements every provider lifecycle hook. After N requests
with distinct tenant headers and a clean lifespan exit, count how many hooks ran on the durable
instances. Also checks: (a) durable instances are not eagerly created at startup, (b) singleton
providers in the same module DO get their hooks (control), (c) durable dict is not read by any
lifecycle code.
"""
from __future__ import annotations

import sys

from starlette.requests import Request
from starlette.testclient import TestClient

from bustan import Controller, Get, Injectable, Module, Scope, create_app

opened: list[object] = []
hook_calls: dict[str, int] = {
    "on_module_init": 0,
    "on_application_bootstrap": 0,
    "before_application_shutdown": 0,
    "on_application_shutdown": 0,
    "on_module_destroy": 0,
}
singleton_hook_calls: dict[str, int] = dict(hook_calls)


@Injectable(scope=Scope.DURABLE)
class TenantPool:
    def __init__(self) -> None:
        opened.append(self)

    @classmethod
    def get_durable_context_key(cls, request: Request | None):
        return request.headers.get("x-tenant-id") if request is not None else None

    def on_module_init(self) -> None:
        hook_calls["on_module_init"] += 1

    def on_application_bootstrap(self) -> None:
        hook_calls["on_application_bootstrap"] += 1

    async def before_application_shutdown(self, signal) -> None:
        hook_calls["before_application_shutdown"] += 1

    async def on_application_shutdown(self, signal) -> None:
        hook_calls["on_application_shutdown"] += 1

    async def on_module_destroy(self) -> None:
        hook_calls["on_module_destroy"] += 1


@Injectable()
class SingletonControl:
    def on_module_init(self) -> None:
        singleton_hook_calls["on_module_init"] += 1

    def on_application_bootstrap(self) -> None:
        singleton_hook_calls["on_application_bootstrap"] += 1

    async def before_application_shutdown(self, signal) -> None:
        singleton_hook_calls["before_application_shutdown"] += 1

    async def on_application_shutdown(self, signal) -> None:
        singleton_hook_calls["on_application_shutdown"] += 1

    async def on_module_destroy(self) -> None:
        singleton_hook_calls["on_module_destroy"] += 1


@Controller("/t", scope=Scope.REQUEST)
class TenantController:
    def __init__(self, pool: TenantPool) -> None:
        self.pool = pool

    @Get("/")
    def read(self) -> dict:
        return {"ok": True}


@Module(controllers=[TenantController], providers=[TenantPool, SingletonControl])
class AppModule:
    pass


N = int(sys.argv[1]) if len(sys.argv) > 1 else 50
app = create_app(AppModule)
sm = app.container.scope_manager

with TestClient(app) as client:
    # lifespan startup ran here
    print("after startup: durable_instances =", len(sm.durable_instances),
          "| opened =", len(opened),
          "| singletons keys =", [k[1].__name__ for k in sm.singletons])
    eager_durable = len(opened)
    for i in range(N):
        r = client.get("/t/", headers={"x-tenant-id": f"tenant-{i}"})
        assert r.status_code == 200, r.text
    print("after requests: durable_instances =", len(sm.durable_instances), "| opened =", len(opened))
    print("durable instances present in scope_manager.singletons:",
          any(isinstance(v, TenantPool) for v in sm.singletons.values()))
# lifespan shutdown ran here

print("durable hook calls:", hook_calls)
print("singleton (control) hook calls:", singleton_hook_calls)
total_durable_hooks = sum(hook_calls.values())
print(f"opened: {len(opened)} closed by lifecycle hooks: "
      f"{hook_calls['on_application_shutdown']} (on_application_shutdown), "
      f"{hook_calls['on_module_destroy']} (on_module_destroy)")

control_ok = all(v == 1 for v in singleton_hook_calls.values())
if eager_durable == 0 and len(opened) == N and total_durable_hooks == 0 and control_ok:
    print("RESULT: CONFIRMED - durable instances skipped by warmup and by all 5 lifecycle stages "
          "while the singleton control received every hook exactly once")
else:
    print("RESULT: REFUTED/UNEXPECTED - eager_durable=%d opened=%d durable_hooks=%d control_ok=%s"
          % (eager_durable, len(opened), total_durable_hooks, control_ok))
