# ruff: noqa
# Evidence script for finding QA-13 (workflow id F-79) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-79: provider-level lifecycle hook failures and LifecycleManager re-entrancy guards are untested.

Part 1 runs the suite under coverage for bustan.core.lifecycle and checks that the cited lines
(runner.py 68-69, 114-122; manager.py 47, 49, 97-98) are reported as never executed.
Part 2 exercises those exact code paths through the public API to show they currently behave
(so the gap is a missing lock-in, not a live bug).
"""
from __future__ import annotations

import re
import subprocess
import sys
from typing import Any, cast

import anyio
from starlette.testclient import TestClient

from bustan import Injectable, Module, create_app, create_app_context
from bustan.errors import LifecycleError

print("== Part 1: coverage of bustan.core.lifecycle under the full test suite ==")
proc = subprocess.run(
    [sys.executable, "-m", "pytest", "tests", "-q", "-p", "no:cacheprovider",
     "--cov=bustan.core.lifecycle", "--cov-report=term-missing"],
    cwd="/home/user/bustan", capture_output=True, text=True,
)
missing: dict[str, set[int]] = {}
for line in proc.stdout.splitlines():
    m = re.match(r"src/bustan/core/lifecycle/(runner|manager)\.py\s+.*?%\s+(.*)$", line)
    if m:
        print("  ", line.strip())
        nums: set[int] = set()
        for chunk in m.group(2).split(","):
            chunk = chunk.strip().split("->")[0]
            if "-" in chunk:
                a, b = chunk.split("-")
                nums.update(range(int(a), int(b) + 1))
            elif chunk.isdigit():
                nums.add(int(chunk))
        missing[m.group(1)] = nums
expected = {"runner": {68, 69, 115, 116, 117, 118, 119, 120, 121, 122}, "manager": {47, 49, 97, 98}}
cov_ok = all(expected[k] <= missing.get(k, set()) for k in expected)
print("  cited lines uncovered:", cov_ok, "| runner missing:", sorted(missing.get("runner", ())),
      "| manager missing:", sorted(missing.get("manager", ())))

print("== Part 2: the untested paths, exercised through the public API ==")
results: list[bool] = []

# (a) provider on_application_shutdown raises -> collected, others still run, LifecycleError with __cause__
events: list[str] = []

@Injectable
class BadShutdown:
    def on_application_shutdown(self, signal):
        raise RuntimeError("provider shutdown boom")
    def on_module_destroy(self):
        events.append("bad:destroy")

@Injectable
class Healthy:
    def on_application_shutdown(self, signal):
        events.append("healthy:shutdown")
    def on_module_destroy(self):
        events.append("healthy:destroy")

@Module(providers=[BadShutdown, Healthy])
class AppA:
    pass

try:
    with TestClient(cast(Any, create_app(AppA))):
        pass
    print("  (a) FAIL: no LifecycleError")
    results.append(False)
except LifecycleError as exc:
    ok = "BadShutdown.on_application_shutdown failed: provider shutdown boom" in str(exc) and isinstance(exc.__cause__, RuntimeError) and events == ["healthy:shutdown", "healthy:destroy", "bad:destroy"]
    print(f"  (a) provider shutdown failure collected: {exc} | cause={exc.__cause__!r} | events={events} -> {'OK' if ok else 'FAIL'}")
    results.append(ok)

# (b) provider on_module_init raises -> LifecycleError from TestClient.__enter__ and ApplicationContext.init()
@Injectable
class BadInit:
    def on_module_init(self):
        raise RuntimeError("provider init boom")

@Module(providers=[BadInit])
class AppB:
    pass

try:
    with TestClient(cast(Any, create_app(AppB))):
        pass
    print("  (b) FAIL: no LifecycleError from TestClient")
    results.append(False)
except LifecycleError as exc:
    ok = "BadInit.on_module_init failed: provider init boom" in str(exc)
    print(f"  (b) provider init failure raised at startup (HTTP): {exc} -> {'OK' if ok else 'FAIL'}")
    results.append(ok)

async def ctx_init_fail() -> bool:
    ctx = create_app_context(AppB)
    try:
        await ctx.init()
    except LifecycleError as exc:
        print(f"  (b') provider init failure raised from ApplicationContext.init(): {exc}")
        return True
    return False
results.append(anyio.run(ctx_init_fail))

# (c) two failing teardown hooks -> aggregated LifecycleError message
@Injectable
class Bad1:
    def on_application_shutdown(self, signal):
        raise RuntimeError("one")

@Injectable
class Bad2:
    def on_module_destroy(self):
        raise ValueError("two")

@Module(providers=[Bad1, Bad2])
class AppC:
    pass

try:
    with TestClient(cast(Any, create_app(AppC))):
        pass
    print("  (c) FAIL: no LifecycleError")
    results.append(False)
except LifecycleError as exc:
    ok = str(exc).startswith("2 lifecycle hooks failed during shutdown:") and "one" in str(exc) and "two" in str(exc)
    print(f"  (c) aggregated: {exc} -> {'OK' if ok else 'FAIL'}")
    results.append(ok)

# (d) LifecycleManager re-entrancy: init twice, close twice, init after close
ev: list[str] = []

@Module()
class Root:
    def on_module_init(self): ev.append("init")
    def on_module_destroy(self): ev.append("destroy")

async def reentry() -> bool:
    ctx = create_app_context(Root)
    await ctx.close()  # close before init: no-op
    await ctx.init(); await ctx.init()
    await ctx.close(); await ctx.close()
    idem = ev == ["init", "destroy"]
    try:
        await ctx.init()
        print("  (d) FAIL: init after close did not raise")
        return False
    except LifecycleError as exc:
        print(f"  (d) idempotent init/close events={ev}; init after close -> {exc} -> {'OK' if idem else 'FAIL'}")
        return idem and "already closed" in str(exc)
results.append(anyio.run(reentry))

# (e) module class whose __init__ needs arguments -> LifecycleError (runner.py:68-69)
@Module()
class NeedsArgs:
    def __init__(self, dependency: object) -> None:
        self.dependency = dependency
    def on_module_init(self) -> None:
        pass

# Note: create_app(NeedsArgs) never reaches runner.py:68-69 because compile_middleware_registry
# (src/bustan/pipeline/middleware.py:158) calls node.module() first and lets the raw TypeError escape.
try:
    create_app(NeedsArgs)
    print("  (e0) create_app(NeedsArgs): no error")
except TypeError as exc:
    print(f"  (e0) create_app(NeedsArgs) raises raw TypeError from middleware.py:158 before lifecycle: {exc}")
except LifecycleError as exc:
    print(f"  (e0) create_app(NeedsArgs) -> LifecycleError: {exc}")

async def needs_args() -> bool:
    ctx = create_app_context(NeedsArgs)
    try:
        await ctx.init()
    except LifecycleError as exc:
        ok = "Could not instantiate module" in str(exc) and isinstance(exc.__cause__, TypeError)
        print(f"  (e) create_app_context: module needing ctor args -> {exc} -> {'OK' if ok else 'FAIL'}")
        return ok
    print("  (e) FAIL: no LifecycleError")
    return False
results.append(anyio.run(needs_args))

if cov_ok and all(results):
    print("RESULT: CONFIRMED - cited runner.py/manager.py lines are uncovered by the suite, and every scenario "
          "currently behaves correctly (the gap is missing lock-in tests, not a live defect)")
else:
    print("RESULT: REFUTED/UNEXPECTED - cov_ok=%s results=%s" % (cov_ok, results))
