# ruff: noqa
# Evidence script for finding PN-02 (workflow id F-10) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-10: singleton factory returning None is never cached (sync re-runs; async breaks init())."""
from __future__ import annotations

import asyncio

from bustan import Module, create_app_context
from bustan.core.errors import ProviderResolutionError

calls = {"sync_none": 0, "falsy_zero": 0, "async_none": 0, "async_value": 0}


def sync_none_factory():
    calls["sync_none"] += 1
    return None


def falsy_zero_factory():
    calls["falsy_zero"] += 1
    return 0


async def async_none_factory():
    calls["async_none"] += 1
    return None


async def async_value_factory():
    calls["async_value"] += 1
    return "ready"


@Module(providers=[
    {"provide": "sync_none", "use_factory": sync_none_factory},
    {"provide": "falsy_zero", "use_factory": falsy_zero_factory},
])
class SyncModule:
    pass


@Module(providers=[{"provide": "async_none", "use_factory": async_none_factory}])
class AsyncNoneModule:
    pass


@Module(providers=[{"provide": "async_value", "use_factory": async_value_factory}])
class AsyncValueModule:
    pass


async def main() -> None:
    verdicts: list[bool] = []

    ctx = create_app_context(SyncModule)
    await ctx.init()
    after_init = calls["sync_none"]
    for _ in range(3):
        assert ctx.get("sync_none") is None
    for _ in range(3):
        assert ctx.get("falsy_zero") == 0
    key_present = any(k[1] == "sync_none" for k in ctx.container.scope_manager.singletons)
    print(f"sync None factory: calls after init()={after_init}, after init()+3 gets={calls['sync_none']} (singleton contract requires 1)")
    print(f"sync None factory: cache dict holds key={key_present} but ScopeManager.get_singleton returns None -> treated as uncached")
    print(f"control falsy 0 factory: calls after init()+3 gets={calls['falsy_zero']} (cached correctly)")
    verdicts.append(calls["sync_none"] == 4 and calls["falsy_zero"] == 1)

    ctx2 = create_app_context(AsyncNoneModule)
    init_error = ""
    try:
        await ctx2.init()
    except ProviderResolutionError as exc:
        init_error = str(exc)
    print(f"async None factory: init() -> {init_error or 'OK'!r}; factory calls={calls['async_none']}")
    verdicts.append("Initialize the application before resolving it synchronously" in init_error)
    for _ in range(3):
        await ctx2.container.resolve_async("async_none", module=ctx2.container.module_graph.root_key)
    print(f"async None factory: after 3 resolve_async calls factory calls={calls['async_none']} (expected 1)")
    verdicts.append(calls["async_none"] == 4)

    ctx3 = create_app_context(AsyncValueModule)
    await ctx3.init()
    for _ in range(3):
        assert ctx3.get("async_value") == "ready"
    print(f"control async non-None factory: init() OK, calls after init()+3 sync gets={calls['async_value']} (cached correctly)")
    verdicts.append(calls["async_value"] == 1)

    print()
    if all(verdicts):
        print("RESULT: CONFIRMED - None-returning singleton factories are never cached; sync re-runs each resolve, async None factory makes init() raise")
    else:
        print("RESULT: NOT FULLY REPRODUCED", verdicts)


asyncio.run(main())
