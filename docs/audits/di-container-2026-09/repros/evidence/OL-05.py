# ruff: noqa
# Evidence script for finding OL-05 (workflow id F-37) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-37: startup failure after on_module_init -> no teardown, LifecycleState unset.

Scenario: PoolModule.on_module_init and Pool.on_module_init run (resource opened),
then the root module's on_application_bootstrap raises. Checks:
  (a) ApplicationContext: init() raises; close() is a no-op (no destroy hooks);
      state is initialized=False, module_instances={}.
  (b) HTTP app via TestClient: lifespan startup fails; shutdown never attempted.
"""
from __future__ import annotations

from typing import Any, cast

import anyio
from starlette.testclient import TestClient

from bustan import Injectable, Module, create_app, create_app_context
from bustan.errors import LifecycleError

events: list[str] = []


@Injectable
class Pool:
    def on_module_init(self) -> None:
        events.append("pool:open")

    def before_application_shutdown(self, signal: str | None) -> None:
        events.append("pool:before_shutdown")

    def on_application_shutdown(self, signal: str | None) -> None:
        events.append("pool:shutdown")

    def on_module_destroy(self) -> None:
        events.append("pool:close")


@Module(providers=[Pool], exports=[Pool])
class PoolModule:
    def on_module_init(self) -> None:
        events.append("poolmodule:init")

    def on_module_destroy(self) -> None:
        events.append("poolmodule:destroy")


@Module(imports=[PoolModule])
class BrokenBootstrap:
    def on_application_bootstrap(self) -> None:
        raise RuntimeError("bootstrap boom")


failures: list[str] = []


async def ctx_case() -> None:
    ctx = create_app_context(BrokenBootstrap)
    try:
        await ctx.init()
        failures.append("init() did not raise")
    except LifecycleError as exc:
        print("init() raised LifecycleError:", exc)
    print("events after failed init():", events)
    before = list(events)
    await ctx.close()
    print("events after close():", events)
    state = ctx._lifecycle_manager.state  # type: ignore[union-attr]
    print("lifecycle state:", state)
    teardown_ran = events != before
    if teardown_ran:
        failures.append("close() ran teardown hooks after partial startup")
    if state.initialized or state.module_instances:
        failures.append("state records partial startup")
    print(
        "CONTEXT CASE:",
        "teardown_ran=%s initialized=%s module_instances=%s"
        % (teardown_ran, state.initialized, dict(state.module_instances)),
    )


anyio.run(ctx_case)

events.clear()
print("--- HTTP app via TestClient ---")
try:
    with TestClient(cast(Any, create_app(BrokenBootstrap))):
        pass
    failures.append("TestClient did not raise")
except LifecycleError as exc:
    print("TestClient raised LifecycleError:", exc)
except Exception as exc:  # starlette may wrap
    print("TestClient raised:", type(exc).__name__, exc)
print("events after failed lifespan:", events)
if any("close" in e or "destroy" in e or "shutdown" in e for e in events):
    failures.append("HTTP teardown ran")

if failures:
    print("REFUTED (framework already tears down):", failures)
else:
    print(
        "CONFIRMED: after on_module_init opened resources and on_application_bootstrap "
        "failed, no shutdown/destroy hook ran and LifecycleState stayed uninitialized"
    )
