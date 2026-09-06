# ruff: noqa
# Evidence script for finding CR-03 (workflow id F-21) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-21: sync DI construction on the event-loop thread acquires a threading.Lock that a
worker thread (sync handler path) is holding while it runs a slow constructor for an
uncached DURABLE key; the loop thread blocks in `with lock:` and every other task stalls.

Part A: container-level reproduction (exact mechanics: resolver.py:139-149, scopes.py:87-92).
Part B: end-to-end HTTP reproduction through TestClient: request 1 (sync handler in an anyio
worker thread) resolves TenantPool lazily; request 2 (request-scoped controller that depends
on TenantPool) is built by execute_http_route on the loop thread (execution.py:122) and
blocks; request 3 (/ping, trivial async handler) cannot be served meanwhile.
"""
from __future__ import annotations

import threading
import time
from typing import Annotated, Any, cast

import anyio
from anyio import to_thread
from starlette.requests import Request
from starlette.testclient import TestClient

from bustan import Controller, Get, Inject, Injectable, Module, Scope, create_app
from bustan.kernel.ioc.container import build_container
from bustan.kernel.ioc.tokens import APPLICATION
from bustan.kernel.module.graph import build_module_graph

CTOR_SLEEP = 1.0


@Injectable(scope=Scope.DURABLE)
class TenantPool:
    built_on: list[str] = []

    def __init__(self) -> None:
        TenantPool.built_on.append(threading.current_thread().name)
        time.sleep(CTOR_SLEEP)  # slow I/O in a constructor; releases the GIL

    @classmethod
    def get_durable_context_key(cls, request: Request | None) -> str:
        return "tenant-a"


@Module(providers=[TenantPool], exports=[TenantPool])
class PoolModule:
    pass


# ---------------------------------------------------------------- Part A
def part_a() -> bool:
    container = build_container(build_module_graph(PoolModule))
    result: dict[str, float] = {}

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

        async with anyio.create_task_group() as tg:
            tg.start_soon(heartbeat)
            tg.start_soon(
                to_thread.run_sync, lambda: container.resolve(TenantPool, module=PoolModule)
            )
            await anyio.sleep(0.2)  # worker thread is now inside the ctor, holding the durable lock
            t0 = time.perf_counter()
            container.resolve(TenantPool, module=PoolModule)  # loop-thread sync resolve
            result["blocked"] = time.perf_counter() - t0
            await anyio.sleep(0.05)  # let the heartbeat wake once and record the gap
            tg.cancel_scope.cancel()
        result["max_gap"] = max(gaps)

    anyio.run(main)
    print(
        "A: loop-thread resolve() blocked %.3f s; max event-loop heartbeat gap %.3f s; "
        "instances built on threads=%s" % (result["blocked"], result["max_gap"], TenantPool.built_on)
    )
    return result["blocked"] > 0.5 and result["max_gap"] > 0.5


# ---------------------------------------------------------------- Part B (HTTP)
@Controller("/slow")
class SlowController:
    """Singleton controller; its sync handler resolves TenantPool lazily in a worker thread."""

    def __init__(self, app: Annotated[object, Inject(APPLICATION)]) -> None:
        self.container = cast(Any, app).container

    @Get("/")
    def slow(self) -> dict[str, str]:
        self.container.resolve(TenantPool, module=PoolModule)
        return {"thread": threading.current_thread().name}


@Controller("/pool", scope=Scope.REQUEST)
class PoolController:
    """Request-scoped controller: constructed by execute_http_route on the loop thread."""

    def __init__(self, pool: TenantPool) -> None:
        self.pool = pool

    @Get("/")
    async def get(self) -> dict[str, str]:
        return {"pool": "ok"}


@Controller("/ping")
class PingController:
    @Get("/")
    async def ping(self) -> dict[str, str]:
        return {"pong": "ok"}


@Module(imports=[PoolModule], controllers=[SlowController, PoolController, PingController])
class AppModule:
    pass


def run_http(with_pool: bool) -> dict[str, float]:
    """Return latencies. with_pool=False is the control: only /slow in flight (worker thread
    holds the lock, loop thread free). with_pool=True adds /pool so the loop thread blocks."""
    app = create_app(AppModule)  # fresh container -> durable cache empty
    timings: dict[str, float] = {}
    with TestClient(cast(Any, app)) as client:
        assert client.get("/ping").status_code == 200  # warm the portal

        def hit(name: str, path: str) -> None:
            t0 = time.perf_counter()
            r = client.get(path)
            timings[name] = time.perf_counter() - t0
            assert r.status_code == 200, (path, r.status_code, r.text)

        threads = [threading.Thread(target=hit, args=("slow", "/slow"))]
        threads[0].start()
        time.sleep(0.2)  # worker thread now inside TenantPool.__init__ holding the durable lock
        if with_pool:
            threads.append(threading.Thread(target=hit, args=("pool", "/pool")))
            threads[-1].start()
            time.sleep(0.2)  # loop thread now blocked in `with lock:` inside resolve()
        hit("ping", "/ping")
        for t in threads:
            t.join()
    return timings


def part_b() -> bool:
    TenantPool.built_on.clear()
    control = run_http(with_pool=False)
    print(
        "B control (no loop-thread resolve): /slow %.3f s, /ping %.3f s while worker holds the lock"
        % (control["slow"], control["ping"])
    )
    stalled = run_http(with_pool=True)
    print(
        "B stall: /slow %.3f s (owns the constructor), /pool %.3f s (loop-thread resolve blocked), "
        "/ping %.3f s (trivial async handler issued while blocked); built_on=%s"
        % (stalled["slow"], stalled["pool"], stalled["ping"], TenantPool.built_on)
    )
    return control["ping"] < 0.15 and stalled["ping"] > 0.3 and len(TenantPool.built_on) == 2


if __name__ == "__main__":
    a = part_a()
    b = part_b()
    print("F-21", "CONFIRMED" if (a and b) else "REFUTED", "- part A stalled:", a, "part B stalled:", b)
