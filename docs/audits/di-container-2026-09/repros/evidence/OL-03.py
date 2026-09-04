# ruff: noqa
# Evidence script for finding OL-03 (workflow id F-16) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-16: bustan.testing re-implements lifecycle orchestration and has drifted:
compile() cannot start graphs with async singleton factories; close() skips before_application_shutdown,
is not idempotent, drops all but the first error, leaves LifecycleManager unaware."""
from __future__ import annotations

import anyio

from bustan import Injectable, Module, create_app_context
from bustan.core.errors import LifecycleError, ProviderResolutionError
from bustan.testing import create_testing_module

checks: dict[str, bool] = {}
events: list[str] = []


@Injectable
class Pool:
    def on_module_init(self) -> None:
        events.append("pool:init")

    def before_application_shutdown(self, signal: str | None) -> None:
        events.append("pool:before_shutdown")

    def on_application_shutdown(self, signal: str | None) -> None:
        events.append("pool:shutdown")

    def on_module_destroy(self) -> None:
        events.append("pool:destroy")


@Module(providers=[Pool])
class HookModule:
    def on_module_init(self) -> None:
        events.append("mod:init")

    def before_application_shutdown(self, signal: str | None) -> None:
        events.append("mod:before_shutdown")

    def on_application_shutdown(self, signal: str | None) -> None:
        events.append("mod:shutdown")

    def on_module_destroy(self) -> None:
        events.append("mod:destroy")


async def build_conn() -> str:
    return "conn"


@Module(providers=[{"provide": "CONN", "use_factory": build_conn}], exports=["CONN"])
class DbModule:
    pass


@Module(imports=[DbModule])
class AsyncApp:
    pass


@Module()
class BrokenA:
    def on_application_shutdown(self, signal: str | None) -> None:
        raise RuntimeError("A failed")


@Module()
class BrokenB:
    def on_module_destroy(self) -> None:
        raise RuntimeError("B failed")


@Module(imports=[BrokenA, BrokenB])
class BrokenRoot:
    pass


async def main() -> None:
    print("-- 1. async singleton factory: create_app_context().init() vs create_testing_module().compile()")
    ctx = await create_app_context(AsyncApp).init()
    print("   create_app_context(...).init() ok, CONN =", ctx.get("CONN"))
    try:
        compiled = await create_testing_module(AsyncApp).compile()
        print("   compile() ok:", compiled.get("CONN"))
        checks["compile_fails_on_async_factory"] = False
    except ProviderResolutionError as exc:
        print("   compile() ProviderResolutionError:", exc)
        checks["compile_fails_on_async_factory"] = "uses an async factory" in str(exc)

    print("-- 2. hook trace after compile()+close()")
    compiled = await create_testing_module(HookModule).compile()
    await compiled.close()
    print("   events:", events)
    checks["before_shutdown_skipped"] = not any("before_shutdown" in e for e in events) and "mod:shutdown" in events

    print("-- 3. second close() re-runs hooks (not idempotent)")
    events.clear()
    await compiled.close()
    print("   events on 2nd close:", events)
    checks["close_not_idempotent"] = "mod:shutdown" in events and "pool:destroy" in events

    print("-- 4. LifecycleManager unaware: application.close() no-op, application.init() re-runs init hooks")
    events.clear()
    compiled2 = await create_testing_module(HookModule).compile()
    print("   after compile(): lifecycle state initialized =",
          compiled2.application._lifecycle_manager.state.initialized, "| events:", events)
    init_count_after_compile = events.count("mod:init")
    events.clear()
    await compiled2.application.close()
    close_events = list(events)
    print("   application.close() ran hooks:", close_events)
    events.clear()
    await compiled2.application.init()
    print("   application.init() ran hooks:", events)
    checks["app_close_noop_and_init_reruns"] = (
        init_count_after_compile == 1 and close_events == [] and events.count("mod:init") == 1
    )

    print("-- 5. control: LifecycleManager path with same module runs all three shutdown stages and is idempotent")
    events.clear()
    ctx2 = await create_app_context(HookModule).init()
    await ctx2.close()
    await ctx2.close()
    print("   events via create_app_context init+close+close:", events)
    checks["manager_control_runs_before_shutdown_once"] = events.count("mod:before_shutdown") == 1 and events.count("mod:shutdown") == 1

    print("-- 6. close() with two failing hooks reports only the first")
    compiled3 = await create_testing_module(BrokenRoot).compile()
    try:
        await compiled3.close()
        print("   no error raised")
        checks["only_first_error"] = False
    except LifecycleError as exc:
        print("   raised:", exc)
        checks["only_first_error"] = "A failed" in str(exc) and "B failed" not in str(exc)
    ctx3 = await create_app_context(BrokenRoot).init()
    try:
        await ctx3.close()
    except LifecycleError as exc:
        print("   control LifecycleManager.shutdown raised:", exc)

    print()
    for k, v in checks.items():
        print(f"   {k}: {v}")
    print("F-16", "CONFIRMED" if all(checks.values()) else "REFUTED")


anyio.run(main)
