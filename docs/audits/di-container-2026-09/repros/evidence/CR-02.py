# ruff: noqa
# Evidence script for finding CR-02 (workflow id F-20) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-20: sync resolve (threading.Lock) vs resolve_async (anyio.Lock) on the same singleton.
Expect: two constructions, one discarded without teardown, loop-thread blocking in _cache_instance."""
from __future__ import annotations

import threading
import time

import anyio

from bustan import Injectable, Module
from bustan.core.ioc.container import build_container
from bustan.core.module.graph import build_module_graph

constructions: list[str] = []


class FakeConn:
    live = 0

    def __init__(self) -> None:
        FakeConn.live += 1

    def close(self) -> None:
        FakeConn.live -= 1


@Injectable
class Pool:
    def __init__(self) -> None:
        constructions.append(threading.current_thread().name)
        self.conn = FakeConn()
        self.destroyed = False
        # simulate slow construction (sync thread slower so async wins the race to build)
        time.sleep(1.0 if threading.current_thread().name == "sync-thread" else 0.2)

    def on_module_destroy(self) -> None:
        self.destroyed = True
        self.conn.close()


@Module(providers=[Pool], exports=[Pool])
class AppModule:
    pass


container = build_container(build_module_graph(AppModule))
results: dict[str, object] = {}


def sync_worker() -> None:
    results["sync"] = container.resolve(Pool, module=AppModule)


async def main() -> None:
    gaps: list[float] = []

    async def heartbeat() -> None:
        last = time.perf_counter()
        with anyio.move_on_after(3.0):
            while True:
                await anyio.sleep(0.01)
                now = time.perf_counter()
                gaps.append(now - last)
                last = now

    t = threading.Thread(target=sync_worker, name="sync-thread")
    t.start()
    await anyio.sleep(0.05)  # sync thread now holds the threading singleton lock and is constructing
    async with anyio.create_task_group() as tg:
        tg.start_soon(heartbeat)
        await anyio.sleep(0)
        t0 = time.perf_counter()
        results["async"] = await container.resolve_async(Pool, module=AppModule)
        results["async_elapsed"] = time.perf_counter() - t0
        await anyio.sleep(0.05)
        tg.cancel_scope.cancel()
    t.join()

    cached = container.scope_manager.singletons[(AppModule, Pool)]
    sync_inst, async_inst = results["sync"], results["async"]
    print("constructions:", constructions)
    print("sync caller got:", "sync-built" if sync_inst is not cached or len(constructions) == 1 else "other")
    print("same instance returned to both callers:", sync_inst is async_inst)
    print("cached instance built on:", "sync-thread" if constructions and cached is sync_inst else "loop (async)")
    print("FakeConn objects still open (>1 means one leaked):", FakeConn.live)
    print("max event-loop heartbeat gap (s): %.3f" % max(gaps))
    print("async resolve elapsed (s): %.3f" % results["async_elapsed"])

    double = len(constructions) == 2
    leaked = FakeConn.live > 1
    loop_blocked = max(gaps) > 0.5
    results["confirmed"] = double and leaked and loop_blocked
    print()
    print("double construction:", double)
    print("discarded instance never torn down (resource leaked):", leaked)
    print("event loop blocked > 0.5s on threading.Lock in _cache_instance:", loop_blocked)
    print("loser instance silently discarded, both callers share the survivor:", sync_inst is async_inst)


anyio.run(main)

# Control: thread-vs-thread sync is already serialized (existing regression test covers it)
constructions.clear()
FakeConn.live = 0
container2 = build_container(build_module_graph(AppModule))
outs: list[object] = []
threads = [threading.Thread(target=lambda: outs.append(container2.resolve(Pool, module=AppModule)), name=f"w{i}") for i in range(3)]
for th in threads:
    th.start()
for th in threads:
    th.join()
print("[control] 3 sync threads: constructions =", len(constructions), "| all same instance:", all(o is outs[0] for o in outs))

print("F-20", "CONFIRMED" if results["confirmed"] else "REFUTED")
