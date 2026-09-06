# ruff: noqa
# Evidence script for finding CR-06 (workflow id F-48) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-48: get_durable_context_key is called several times per uncached resolve; a key that is not stable
within one resolve defeats caching and grows caches; an unhashable key surfaces as a raw TypeError.
"""
from __future__ import annotations

import itertools

import anyio
from starlette.requests import Request

from bustan import Injectable, Module, Scope
from bustan.kernel.errors import ProviderResolutionError
from bustan.kernel.ioc.container import build_container
from bustan.kernel.module.graph import build_module_graph

calls: list[int] = []
counter = itertools.count()
MODE = {"key": "stable"}


@Injectable(scope=Scope.DURABLE)
class Durable:
    @classmethod
    def get_durable_context_key(cls, request: Request | None) -> object:
        calls.append(1)
        if MODE["key"] == "stable":
            return "tenant-a"
        if MODE["key"] == "fresh":
            return next(counter)
        return ["x"]


@Module(providers=[Durable], exports=[Durable])
class AppModule:
    pass


def fresh_container():
    return build_container(build_module_graph(AppModule))


results: dict[str, object] = {}

# ---- sync path: call counts
c = fresh_container()
calls.clear()
c.resolve(Durable, module=AppModule)
results["sync_uncached_calls"] = len(calls)
calls.clear()
c.resolve(Durable, module=AppModule)
results["sync_cached_calls"] = len(calls)
print("sync: key calls on uncached resolve =", results["sync_uncached_calls"], "; on cached resolve =", results["sync_cached_calls"])


# ---- async path: call counts
async def async_part() -> None:
    c2 = fresh_container()
    calls.clear()
    await c2.resolve_async(Durable, module=AppModule)
    results["async_uncached_calls"] = len(calls)
    calls.clear()
    await c2.resolve_async(Durable, module=AppModule)
    results["async_cached_calls"] = len(calls)
    print("async: key calls on uncached resolve =", results["async_uncached_calls"], "; on cached resolve =", results["async_cached_calls"])

    MODE["key"] = "fresh"
    c3 = fresh_container()
    seen = set()
    for _ in range(100):
        seen.add(id(await c3.resolve_async(Durable, module=AppModule)))
    sm = c3.scope_manager
    results["async_fresh"] = (len(seen), len(sm.durable_instances), len(sm.durable_locks), len(sm.async_construction_locks))
    print("async fresh-key x100: distinct instances=%d durable_instances=%d durable_locks=%d async_construction_locks=%d" % results["async_fresh"])
    MODE["key"] = "stable"


anyio.run(async_part)

# ---- sync path with a non-deterministic key
MODE["key"] = "fresh"
c4 = fresh_container()
a1 = c4.resolve(Durable, module=AppModule)
a2 = c4.resolve(Durable, module=AppModule)
results["sync_fresh"] = (a1 is a2, len(c4.scope_manager.durable_instances), len(c4.scope_manager.durable_locks))
print("sync fresh-key x2: same instance=%s durable_instances=%d durable_locks=%d" % results["sync_fresh"])

# ---- unhashable key
MODE["key"] = "unhashable"
c5 = fresh_container()
try:
    c5.resolve(Durable, module=AppModule)
    results["unhashable"] = "no error"
except ProviderResolutionError as exc:
    results["unhashable"] = f"ProviderResolutionError: {exc}"
except Exception as exc:  # noqa: BLE001
    results["unhashable"] = f"{type(exc).__name__}: {exc}"
print("unhashable key ->", results["unhashable"])

ok = (
    results["sync_uncached_calls"] >= 3
    and results["async_uncached_calls"] >= 3
    and results["sync_fresh"][0] is False
    and results["sync_fresh"][1] >= 2  # one new cache entry per resolve
    and results["async_fresh"][1] >= 100
    and results["unhashable"].startswith("TypeError")
)
print("PASS: multiple key calls per resolve, unstable key defeats caching and grows caches, unhashable key -> raw TypeError"
      if ok else "FAIL: behavior differs from the finding")
