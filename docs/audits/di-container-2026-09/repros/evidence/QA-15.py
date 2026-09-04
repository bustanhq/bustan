# ruff: noqa
# Evidence script for finding QA-15 (workflow id F-81) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-81: untested categories - override-by-scope matrix, durable over HTTP, durable lifecycle/eviction,
dynamic-module overrides.

Part 1: grep the test tree for any test touching these categories.
Part 2: demonstrate each currently-untested behaviour via the public API.
"""
from __future__ import annotations

import re
import subprocess
from typing import Annotated, Any, cast

from starlette.requests import Request
from starlette.testclient import TestClient

from bustan import Controller, DynamicModule, Get, Inject, Injectable, Module, Scope, create_app
from bustan.core.errors import ProviderResolutionError
from bustan.testing import override_provider

print("== Part 1: what the test tree covers ==")
def rg(pattern: str, path: str = "tests") -> list[str]:
    out = subprocess.run(["grep", "-rln", "--include=*.py", "-E", pattern, path], cwd="/home/user/bustan",
                         capture_output=True, text=True).stdout.split()
    return out
print("  files using override_provider/provider_overrides:", rg(r"override_provider|provider_overrides"))
print("  of those, any mentioning REQUEST/DURABLE/TRANSIENT/use_existing:",
      [f for f in rg(r"override_provider|provider_overrides") if re.search(r"DURABLE|REQUEST|TRANSIENT|use_existing", open("/home/user/bustan/" + f).read())])
print("  files mentioning Scope.DURABLE / durable:", rg(r"Scope\.DURABLE|DURABLE|durable"))
print("  files using TestClient AND durable:", [f for f in rg(r"TestClient") if re.search(r"DURABLE|durable", open("/home/user/bustan/" + f).read())])
print("  files referencing durable_instances/durable_locks:", rg(r"durable_instances|durable_locks"))
print("  test_dynamic_modules.py mentions override:", bool(re.search(r"override", open("/home/user/bustan/tests/unit/core/module/test_dynamic_modules.py").read())))
print("  files with DynamicModule AND override:", [f for f in rg(r"DynamicModule") if re.search(r"override", open("/home/user/bustan/" + f).read())])

print("== Part 2: behaviours currently unpinned ==")
results: list[bool] = []

# --- override matrix over HTTP ---
@Injectable(scope=Scope.REQUEST)
class ReqSvc:
    def __init__(self, request: Request):
        self.request = request
    def name(self): return "real-req"

@Injectable(scope=Scope.TRANSIENT)
class TransSvc:
    def name(self): return "real-trans"

@Injectable(scope=Scope.DURABLE)
class DurSvc:
    @classmethod
    def get_durable_context_key(cls, request): return request.headers.get("x-tenant")
    def name(self): return "real-dur"

@Controller("/c", scope=Scope.REQUEST)
class C:
    def __init__(self, r: ReqSvc, t: TransSvc, d: DurSvc, alias: Annotated[Any, Inject("alias")]):
        self.r, self.t, self.d, self.alias = r, t, d, alias
    @Get("/")
    def read(self) -> dict:
        return {"r": self.r.name(), "t": self.t.name(), "d": self.d.name(), "alias": self.alias.name(),
                "d_id": id(self.d)}

@Module(controllers=[C], providers=[ReqSvc, TransSvc, DurSvc, {"provide": "alias", "use_existing": TransSvc}])
class AppModule:
    pass

class Fake:
    def __init__(self, n): self.n = n
    def name(self): return self.n

app = create_app(AppModule)
with TestClient(cast(Any, app)) as client:
    base = client.get("/c/", headers={"x-tenant": "a"}).json()
    print("  baseline:", base)
    with override_provider(app, ReqSvc, Fake("fake-req")), override_provider(app, TransSvc, Fake("fake-trans")), override_provider(app, DurSvc, Fake("fake-dur")):
        oa = client.get("/c/", headers={"x-tenant": "a"}).json()
        ob = client.get("/c/", headers={"x-tenant": "b"}).json()
        print("  overridden tenant a:", oa)
        print("  overridden tenant b:", ob)
        results.append(oa["r"] == "fake-req" and oa["t"] == "fake-trans" and oa["d"] == "fake-dur" and oa["alias"] == "fake-trans")
        results.append(oa["d_id"] == ob["d_id"])  # one fake shared by every tenant
    rest = client.get("/c/", headers={"x-tenant": "a"}).json()
    print("  restored:", rest); results.append(rest["r"] == "real-req" and rest["alias"] == "real-trans")
    app.container.override(ReqSvc, Fake("no-request-needed"))
    v = cast(Any, app.container.resolve(ReqSvc, module=AppModule)).name()
    print("  request-scoped override resolved with NO active request:", v); results.append(v == "no-request-needed")
    app.container.clear_override(ReqSvc)

# --- durable over HTTP: None key partition, destroy hooks, cache growth ---
destroy_events: list[str] = []

@Injectable(scope=Scope.DURABLE)
class Tenant:
    n = 0
    @classmethod
    def get_durable_context_key(cls, request): return request.headers.get("x-tenant")
    def __init__(self):
        Tenant.n += 1; self.id = Tenant.n
    def on_module_destroy(self): destroy_events.append(f"destroy:{self.id}")

@Controller("/t", scope=Scope.REQUEST)
class TC:
    def __init__(self, t: Tenant): self.t = t
    @Get("/")
    def read(self) -> dict: return {"tenant_instance": self.t.id}

@Module(controllers=[TC], providers=[Tenant])
class DurModule: pass

app2 = create_app(DurModule)
with TestClient(cast(Any, app2)) as client:
    a1 = client.get("/t/", headers={"x-tenant": "a"}).json()["tenant_instance"]
    b1 = client.get("/t/", headers={"x-tenant": "b"}).json()["tenant_instance"]
    a2 = client.get("/t/", headers={"x-tenant": "a"}).json()["tenant_instance"]
    print("  HTTP partitioning a1/b1/a2:", a1, b1, a2); results.append(a1 == a2 and a1 != b1)
    r1 = client.get("/t/"); r2 = client.get("/t/")
    print("  no tenant header -> status", r1.status_code, "instances", r1.json(), r2.json())
    results.append(r1.status_code == 200 and r1.json() == r2.json())
    keys = list(app2.container.scope_manager.durable_instances.keys())
    print("  durable cache keys:", [(k[0].__name__ if hasattr(k[0], "__name__") else k[0], k[1].__name__, k[2]) for k in keys])
    results.append(any(k[2] is None for k in keys))
    for i in range(100):
        client.get("/t/", headers={"x-tenant": f"tenant-{i}"})
    n_keys = len(app2.container.scope_manager.durable_instances)
    print("  durable cache size after 100 more tenants:", n_keys, "| eviction API on ScopeManager:",
          [a for a in dir(app2.container.scope_manager) if "evict" in a or "clear" in a])
    results.append(n_keys >= 103)
print("  destroy events after lifespan shutdown:", destroy_events, "| instances created:", Tenant.n)
results.append(destroy_events == [])

# --- dynamic-module overrides: overrides.py:47 ambiguity path ---
@Module()
class ConfigModule: pass

dyn1 = DynamicModule(ConfigModule, providers=({"provide": "CONFIG", "use_value": 1},), exports=("CONFIG",))
dyn2 = DynamicModule(ConfigModule, providers=({"provide": "CONFIG", "use_value": 2},), exports=("CONFIG",))

@Controller("/cfg")
class CfgController:
    def __init__(self, cfg: Annotated[int, Inject("CONFIG")]): self.cfg = cfg
    @Get("/")
    def read(self) -> dict: return {"cfg": self.cfg}

@Module(imports=[dyn1, dyn2], controllers=[CfgController])
class DynApp: pass

app3 = create_app(DynApp)
with TestClient(cast(Any, app3)) as client:
    print("  importer of two same-token dynamic exports receives:", client.get("/cfg/").json())
    try:
        app3.container.override("CONFIG", 99)
        print("  override('CONFIG') without module: no error (FAIL - expected ambiguity)"); results.append(False)
    except ProviderResolutionError as exc:
        print("  override('CONFIG') without module -> ambiguity error:", exc); results.append(True)
    keys = [k for k in app3.container.registry.bindings if k[1] == "CONFIG"]
    with override_provider(app3, "CONFIG", 99, module_cls=cast(Any, keys[0][0])):
        print("  override by first ModuleInstanceKey -> importer sees:", client.get("/cfg/").json())

print("  results:", results)
if all(results):
    print("RESULT: CONFIRMED - override matrix (request/durable/transient/use_existing) works but is unpinned; durable "
          "None key is a shared 200 partition; durable destroy hooks never run; durable cache has no eviction; "
          "dynamic-module override ambiguity path is untested")
else:
    print("RESULT: REFUTED/UNEXPECTED - see results above")
