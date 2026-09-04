# ruff: noqa
# Evidence script for finding OL-13 (workflow id F-57) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-57: shutdown() leaves ScopeManager caches populated and startup() is one-shot.

Checks:
  A. ctx.init(); ctx.close() runs on_module_destroy; ctx.get(Pool) still returns the destroyed instance.
  B. ctx.init() after close() raises LifecycleError.
  C. Same Application object entered twice via TestClient -> second enter raises LifecycleError.
  D. Is there any public reset API on ApplicationContext / LifecycleManager / ScopeManager?
"""
from __future__ import annotations

from typing import Any, cast

import anyio
from starlette.testclient import TestClient

from bustan import Injectable, Module, create_app, create_app_context
from bustan.app.application import ApplicationContext
from bustan.core.ioc.scopes import ScopeManager
from bustan.core.lifecycle.manager import LifecycleManager
from bustan.errors import LifecycleError

events: list[str] = []


@Injectable
class Pool:
    def __init__(self) -> None:
        self.open = False

    def on_module_init(self) -> None:
        self.open = True
        events.append("pool:open")

    def on_module_destroy(self) -> None:
        self.open = False
        events.append("pool:close")


@Module(providers=[Pool], exports=[Pool])
class PoolModule:
    pass


@Module(imports=[PoolModule])
class AppModule:
    pass


results: dict[str, bool] = {}


async def context_case() -> None:
    ctx = create_app_context(AppModule)
    await ctx.init()
    pool1 = ctx.get(Pool)
    print("after init: pool.open =", pool1.open, "events =", events)
    await ctx.close()
    print("after close: events =", events, "| lifecycle state =", ctx._lifecycle_manager.state)
    pool2 = ctx.get(Pool)
    same = pool1 is pool2
    print("get(Pool) after close -> same destroyed instance:", same, "| pool.open =", pool2.open)
    print("scope_manager.singletons still populated:", len(ctx.container.scope_manager.singletons))
    results["A_serves_destroyed_singleton"] = same and pool2.open is False
    try:
        await ctx.init()
        print("init() after close(): succeeded (no error)")
        results["B_reinit_raises"] = False
    except LifecycleError as exc:
        print("init() after close() -> LifecycleError:", exc)
        results["B_reinit_raises"] = True


anyio.run(context_case)

events.clear()
app = create_app(AppModule)
with TestClient(cast(Any, app)):
    pass
print("first TestClient block done, events =", events)
try:
    with TestClient(cast(Any, app)):
        pass
    print("second TestClient block on the same Application: OK")
    results["C_second_testclient_fails"] = False
except LifecycleError as exc:
    print("second TestClient block on the same Application -> LifecycleError:", exc)
    results["C_second_testclient_fails"] = True

public = lambda cls: sorted(n for n in dir(cls) if not n.startswith("_"))  # noqa: E731
print("ApplicationContext public API:", public(ApplicationContext))
print("LifecycleManager public API:", public(LifecycleManager))
print("ScopeManager public API:", public(ScopeManager))
has_reset = any(
    "reset" in n or "restart" in n or n in ("clear", "clear_singletons", "dispose")
    for cls in (ApplicationContext, LifecycleManager, ScopeManager)
    for n in public(cls)
)
print("any public reset/restart API found:", has_reset)
results["D_no_reset_api"] = not has_reset

print()
for k, v in results.items():
    print(f"  {k}: {'observed' if v else 'NOT observed'}")
print("RESULT:", "CONFIRMED" if all(results.values()) else "REFUTED", "- F-57")
