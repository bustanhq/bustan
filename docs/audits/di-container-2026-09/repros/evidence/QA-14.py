# ruff: noqa
# Evidence script for finding QA-14 (workflow id F-80) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-80: resolver kernel is tested through private seams; several public paths have no coverage.

Part 1: count direct private-method calls in tests/unit/core/ioc/test_resolver.py.
Part 2: run coverage for bustan.core.ioc and check resolver.py lines 427, 534-535, 610-614, 682 are missing.
Part 3: exercise the allegedly untested public paths (keyword-only, positional-only, OptionalDep via public
API, unknown module, uninspectable __init__, instantiate_class scope inference for request/durable bound
classes) to show what a black-box test would lock in.
"""
from __future__ import annotations

import re
import subprocess
import sys
from typing import Annotated, Any, cast

from starlette.requests import Request

from bustan import Inject, Injectable, Module, OptionalDep, Scope
from bustan.core.errors import ProviderResolutionError
from bustan.core.ioc.container import build_container
from bustan.core.module.graph import build_module_graph
from bustan.core.ioc.tokens import REQUEST

print("== Part 1: private seam calls in test_resolver.py ==")
src = open("/home/user/bustan/tests/unit/core/ioc/test_resolver.py").read()
calls = re.findall(r"resolver\.(_[a-z_]+)\(", src)
from collections import Counter
counts = Counter(calls)
print("  total direct private calls:", len(calls), dict(counts))
print("  public container.resolve/instantiate_class calls in that file:",
      len(re.findall(r"container\.(resolve|instantiate_class)\(", src)))

print("== Part 2: coverage of resolver.py under the full suite ==")
proc = subprocess.run(
    [sys.executable, "-m", "pytest", "tests", "-q", "-p", "no:cacheprovider",
     "--cov=bustan.core.ioc", "--cov-report=term-missing"],
    cwd="/home/user/bustan", capture_output=True, text=True,
)
missing: set[int] = set()
for line in proc.stdout.splitlines():
    m = re.match(r"src/bustan/core/ioc/resolver\.py\s+.*?%\s+(.*)$", line)
    if m:
        print("  ", line.strip())
        for chunk in m.group(1).split(","):
            chunk = chunk.strip().split("->")[0]
            if "-" in chunk:
                a, b = chunk.split("-")
                missing.update(range(int(a), int(b) + 1))
            elif chunk.isdigit():
                missing.add(int(chunk))
expected = {427, 534, 535, 610, 611, 612, 613, 614, 682}
cov_ok = expected <= missing
print("  cited lines uncovered:", cov_ok, "| missing among cited:", sorted(expected & missing))

print("== Part 3: public-path behaviours a black-box test would lock in ==")
results: list[bool] = []

@Injectable
class Dep:
    pass

class Missing:
    pass

@Injectable
class KwOnly:
    def __init__(self, *, dep: Dep) -> None:
        self.dep = dep

@Injectable
class PosOnly:
    def __init__(self, dep: Dep, /) -> None:
        self.dep = dep

@Injectable
class Optional:
    def __init__(self, maybe: Annotated[Missing | None, OptionalDep()] = None) -> None:
        self.maybe = maybe

@Injectable(scope=Scope.REQUEST)
class ReqBound:
    def __init__(self, request: Annotated[object, Inject(REQUEST)]) -> None:
        self.request = request

@Injectable(scope=Scope.DURABLE)
class DurBound:
    @classmethod
    def get_durable_context_key(cls, request):
        return "k"
    def __init__(self, request: Annotated[object, Inject(REQUEST)]) -> None:
        self.request = request

@Module(providers=[Dep, KwOnly, PosOnly, Optional, ReqBound, DurBound])
class AppModule:
    pass

class NotInGraph:
    pass

container = build_container(build_module_graph(AppModule))

kw = cast(Any, container.resolve(KwOnly, module=AppModule))
print("  keyword-only ctor via container.resolve:", type(kw.dep).__name__); results.append(isinstance(kw.dep, Dep))
po = cast(Any, container.resolve(PosOnly, module=AppModule))
print("  positional-only ctor via container.resolve:", type(po.dep).__name__); results.append(isinstance(po.dep, Dep))
op = cast(Any, container.resolve(Optional, module=AppModule))
print("  OptionalDep on missing class via container.resolve:", op.maybe); results.append(op.maybe is None)
try:
    container.resolve(Dep, module=NotInGraph)
    results.append(False); print("  unknown module: FAIL no error")
except ProviderResolutionError as exc:
    print("  unknown module (resolver.py:427):", exc); results.append("not part of the application container" in str(exc))

# uninspectable __init__ (resolver.py:534-535): a constructor whose __signature__ raises ValueError
class WeirdCtor:
    @property
    def __signature__(self):
        raise ValueError("no signature")
    def __call__(self, *args, **kwargs):
        pass

class Uninspectable:
    __init__ = WeirdCtor()

try:
    container.instantiate_class(Uninspectable, module=AppModule)
    print("  uninspectable __init__: FAIL no error"); results.append(False)
except ProviderResolutionError as exc:
    print("  uninspectable __init__ (resolver.py:534-535):", exc); results.append("Could not inspect" in str(exc))

# bonus: a C slot-wrapper __init__ is inspectable but has no __globals__ -> raw AttributeError at resolver.py:545
class SlotWrapperInit:
    __init__ = type.__call__
try:
    container.instantiate_class(SlotWrapperInit, module=AppModule)
except Exception as exc:
    print("  slot-wrapper __init__ ->", type(exc).__name__, "(resolver.py:545 constructor.__globals__):", exc)

# instantiate_class scope inference (resolver.py:607-615) for a class bound as request / durable
def _req() -> Request:
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET",
             "scheme": "http", "path": "/", "raw_path": b"/", "query_string": b"",
             "headers": [(b"host", b"t")], "client": ("t", 1), "server": ("t", 80), "path_params": {}}
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}
    return Request(scope, receive)

req = _req()
rb = cast(Any, container.instantiate_class(ReqBound, module=AppModule, request=req))
print("  instantiate_class(ReqBound) infers request scope; REQUEST injected:", rb.request is req); results.append(rb.request is req)
db = cast(Any, container.instantiate_class(DurBound, module=AppModule, request=req))
print("  instantiate_class(DurBound) infers durable scope; REQUEST injected:", db.request is req); results.append(db.request is req)
try:
    container.instantiate_class(ReqBound, module=AppModule)
    print("  instantiate_class(ReqBound) without request: no error"); results.append(False)
except ProviderResolutionError as exc:
    print("  instantiate_class(ReqBound) without request ->", exc); results.append(True)

if cov_ok and all(results):
    print("RESULT: CONFIRMED - test_resolver.py drives the kernel through %d private calls; resolver.py lines "
          "427, 534-535, 610-614, 682 are uncovered; the public paths above work but nothing pins them" % len(calls))
else:
    print("RESULT: REFUTED/UNEXPECTED - cov_ok=%s results=%s" % (cov_ok, results))
