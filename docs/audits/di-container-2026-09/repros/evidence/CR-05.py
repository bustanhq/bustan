# ruff: noqa
# Evidence script for finding CR-05 (workflow id F-24) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
# Left naming the pre-rename package tree, on purpose. The packages were renamed after
# this ran - core to kernel, platform/http to runtime, logger to observability, config
# to configuration - but the module this script imports, src/bustan/core/ioc/resolver.py,
# was deleted rather than renamed and has no successor at any path. Renaming the names
# around it would not let it run, and would claim it had measured a tree it never saw.
"""F-24: constructor planning (_plan_constructor_parameters, resolver.py:509-605) is not
memoized: every instantiate_class call re-runs inspect.signature, get_type_hints and
_build_type_hint_namespace (O(visible tokens)); with binding_scope None it also scans
registry.bindings linearly (_detect_owner_scope, resolver.py:607-615).

Measured:
  1. call counts of inspect.signature / get_type_hints / _build_type_hint_namespace /
     _detect_owner_scope per instantiate_class call (wrapping the functions; no repo edits)
  2. per-instantiation wall time at ~30 vs ~1500 visible tokens (linear scaling claim)
  3. cProfile share of _build_type_hint_namespace within _plan_constructor_parameters
"""
from __future__ import annotations

import cProfile
import inspect
import io
import pstats
import sys
import time
import typing
from typing import Any

from starlette.requests import Request

from bustan import Controller, Get, Injectable, Module, Scope
from bustan.core.ioc import resolver as resolver_mod
from bustan.core.ioc.container import build_container
from bustan.core.module.graph import build_module_graph


def build_request() -> Request:
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET",
        "scheme": "http", "path": "/", "raw_path": b"/", "query_string": b"",
        "headers": [(b"host", b"t")], "client": ("c", 1), "server": ("s", 80), "path_params": {},
    }

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(scope, receive)


def make_app(n_providers: int) -> tuple[Any, Any, Any]:
    providers = []
    for i in range(n_providers):
        cls = Injectable(type(f"Svc{i}", (), {"__init__": lambda self: None}))
        providers.append(cls)
    svc0, svc1, svc2 = providers[:3]

    @Injectable(scope=Scope.REQUEST)
    class Identity:
        def __init__(self, request: Request) -> None:
            self.request = request

    ns = {"Svc0": svc0, "Svc1": svc1, "Svc2": svc2, "Identity": Identity}

    @Controller("/x", scope=Scope.REQUEST)
    class XController:
        def __init__(self, a: "Svc0", b: "Svc1", c: "Svc2", ident: "Identity") -> None:
            pass

        @Get("/")
        def get(self) -> dict[str, str]:
            return {}

    # make the string annotations resolvable through the class module globals
    sys.modules[XController.__module__].__dict__.update(ns)

    @Module(controllers=[XController], providers=[*providers, Identity])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    key = container.module_graph.root_key
    for p in providers:  # eager singletons as LifecycleManager.startup does
        container.resolve(p, module=key)
    return container, key, XController


# ---- 1. call counting via wrappers (monkeypatch in-process only)
counts = {"signature": 0, "get_type_hints": 0, "namespace": 0, "detect_owner_scope": 0}
orig_signature = inspect.signature
orig_get_type_hints = typing.get_type_hints
orig_namespace = resolver_mod.Resolver._build_type_hint_namespace
orig_detect = resolver_mod.Resolver._detect_owner_scope


def w_signature(*a: Any, **k: Any) -> Any:
    counts["signature"] += 1
    return orig_signature(*a, **k)


def w_hints(*a: Any, **k: Any) -> Any:
    counts["get_type_hints"] += 1
    return orig_get_type_hints(*a, **k)


def w_namespace(self: Any, *a: Any, **k: Any) -> Any:
    counts["namespace"] += 1
    return orig_namespace(self, *a, **k)


def w_detect(self: Any, *a: Any, **k: Any) -> Any:
    counts["detect_owner_scope"] += 1
    return orig_detect(self, *a, **k)


resolver_mod.inspect.signature = w_signature  # type: ignore[assignment]
resolver_mod.get_type_hints = w_hints  # type: ignore[assignment]
resolver_mod.Resolver._build_type_hint_namespace = w_namespace  # type: ignore[assignment]
resolver_mod.Resolver._detect_owner_scope = w_detect  # type: ignore[assignment]

container_small, key_small, XSmall = make_app(30)
for k in counts:
    counts[k] = 0
N = 100
for _ in range(N):
    container_small.instantiate_class(XSmall, module=key_small, request=build_request())
print(f"1. {N} instantiate_class calls of a request-scoped controller with 4 deps (1 request-scoped):")
for k, v in counts.items():
    print(f"   {k}: {v} calls ({v / N:.1f} per instantiation)")
no_cache = counts["signature"] >= N and counts["get_type_hints"] >= N and counts["namespace"] >= N

# restore wrappers before timing
resolver_mod.inspect.signature = orig_signature  # type: ignore[assignment]
resolver_mod.get_type_hints = orig_get_type_hints  # type: ignore[assignment]
resolver_mod.Resolver._build_type_hint_namespace = orig_namespace  # type: ignore[assignment]
resolver_mod.Resolver._detect_owner_scope = orig_detect  # type: ignore[assignment]


# ---- 2. scaling with visible tokens
def timed(container: Any, key: Any, cls: Any, n: int = 1500) -> float:
    reqs = [build_request() for _ in range(n)]
    for r in reqs[:50]:
        container.instantiate_class(cls, module=key, request=r)
    t0 = time.perf_counter()
    for r in reqs:
        container.instantiate_class(cls, module=key, request=r)
    return (time.perf_counter() - t0) / n


container_big, key_big, XBig = make_app(1500)
us_small = timed(container_small, key_small, XSmall) * 1e6
us_big = timed(container_big, key_big, XBig) * 1e6
print(f"2. per-instantiation: {us_small:.0f} us at 31 visible tokens; {us_big:.0f} us at 1501 visible tokens; ratio {us_big / us_small:.1f}x")

# ---- 3. profile share
pr = cProfile.Profile()
pr.enable()
for _ in range(300):
    container_big.instantiate_class(XBig, module=key_big, request=build_request())
pr.disable()
stream = io.StringIO()
stats = pstats.Stats(pr, stream=stream).sort_stats("cumulative")
stats.print_stats(r"_plan_constructor_parameters|_build_type_hint_namespace|_detect_owner_scope")
lines = [ln for ln in stream.getvalue().splitlines() if "resolver.py" in ln]
print("3. cProfile (cumulative) at 1501 tokens:")
for ln in lines:
    print("   " + ln.strip())


def cum(name: str) -> float:
    for ln in lines:
        if name in ln:
            return float(ln.split()[3])
    return 0.0


plan, ns_share = cum("_plan_constructor_parameters"), cum("_build_type_hint_namespace")
share = (ns_share / plan * 100) if plan else 0.0
print(f"   _build_type_hint_namespace = {share:.0f}% of _plan_constructor_parameters cumulative time")

confirmed = no_cache and us_big / us_small > 2.5
print(
    "F-24", "CONFIRMED" if confirmed else "REFUTED",
    f"- reflection redone every instantiation: {no_cache}; cost grows with visible tokens: {us_big / us_small:.1f}x",
)
