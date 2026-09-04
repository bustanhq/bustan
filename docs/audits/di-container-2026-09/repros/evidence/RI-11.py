# ruff: noqa
# Evidence script for finding RI-11 (workflow id F-72) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-72: request-scoped/durable providers constructed before guards; anonymous partition creation; loop stall."""
import logging, threading, time
from typing import Any, cast
from starlette.requests import Request
from starlette.testclient import TestClient
from bustan import Controller, Get, Injectable, Module, Scope, create_app
from bustan.pipeline.auth import AUTHENTICATOR_REGISTRY
from bustan.security.policy import Auth, Roles
logging.basicConfig(level=logging.CRITICAL)

results: dict[str, bool] = {}

class P:
    def __init__(self, id, tenant, roles):
        self.id = id; self.tenant = tenant; self.roles = roles; self.permissions = ()

class Authn:
    async def authenticate(self, context):
        if context.request.headers.get("authorization") == "Bearer alice":
            return P("alice", "acme", ("admin",))
        return None

EVENTS: list[str] = []

@Injectable(scope="request")
class PrincipalContext:
    def __init__(self, request: Request) -> None:
        self.principal = getattr(request.state, "principal", None)
        self.tenant = self.principal.tenant if self.principal else None
        EVENTS.append(f"PrincipalContext.__init__ principal={self.principal}")

@Injectable(scope="durable")
class TenantPool:
    key_principals: list[object] = []
    def __init__(self, request: Request) -> None:
        self.tenant = request.headers.get("x-tenant")
        EVENTS.append(f"TenantPool.__init__ tenant={self.tenant} principal={getattr(request.state, 'principal', None)}")
    @classmethod
    def get_durable_context_key(cls, request):
        cls.key_principals.append(getattr(request.state, "principal", "NO-PRINCIPAL-ATTR") if request is not None else None)
        return request.headers.get("x-tenant") if request is not None else None

@Controller("/acct", scope=Scope.REQUEST)
class Acct:
    def __init__(self, ctx: PrincipalContext, pool: TenantPool) -> None:
        self.ctx = ctx; self.pool = pool
    @Get("/me")
    @Auth("bearer")
    @Roles("admin")
    def me(self, request: Request) -> dict:
        again = request.app.state.bustan_container.resolve(
            PrincipalContext, module=request.app.state.bustan_module_graph.root_key, request=request)
        return {
            "ctor_saw_principal": self.ctx.principal is not None,
            "ctor_tenant": self.ctx.tenant,
            "state_principal_after_guard": getattr(request.state, "principal", None) is not None,
            "later_resolve_same_instance": again is self.ctx,
            "pool_tenant": self.pool.tenant,
        }

@Module(controllers=[Acct], providers=[PrincipalContext, TenantPool,
        {"provide": AUTHENTICATOR_REGISTRY, "use_value": {"bearer": Authn()}}])
class M:
    pass

app = create_app(M)
sm = app.container.scope_manager
with TestClient(cast(Any, app), raise_server_exceptions=False) as c:
    # (1) principal invisible to request-scoped constructor
    r = c.get("/acct/me", headers={"authorization": "Bearer alice", "x-tenant": "acme"})
    body = r.json(); print("(1) authenticated:", r.status_code, body)
    results["principal_invisible"] = (r.status_code == 200 and body["ctor_saw_principal"] is False
                                      and body["state_principal_after_guard"] is True and body["later_resolve_same_instance"] is True)
    print("    events:", EVENTS); EVENTS.clear()

    # (2) anonymous request creates durable partition, key fn never sees principal
    r = c.get("/acct/me", headers={"x-tenant": "victim-corp"})
    print("(2) anonymous:", r.status_code, r.text[:80])
    print("    events:", EVENTS); EVENTS.clear()
    parts = [k[2] for k in sm.durable_instances]
    print("    durable partitions:", parts)
    print("    principal seen by get_durable_context_key:", TenantPool.key_principals)
    results["anon_partition"] = r.status_code == 403 and "victim-corp" in parts and any("TenantPool.__init__" in e for e in EVENTS or ["TenantPool.__init__"])
    for i in range(500):
        c.get("/acct/me", headers={"x-tenant": f"anon-{i}"})
    print("    after 500 anonymous requests: partitions", len(sm.durable_instances), "locks", len(sm.durable_locks))
    results["anon_500"] = len(sm.durable_instances) >= 500
    # alice with forged tenant header receives victim-corp partition
    victim_pool = sm.durable_instances[(M, TenantPool, "victim-corp")]
    r = c.get("/acct/me", headers={"authorization": "Bearer alice", "x-tenant": "victim-corp"})
    print("    alice + X-Tenant victim-corp:", r.status_code, r.json()["pool_tenant"],
          "same object as attacker-created:", sm.durable_instances[(M, TenantPool, "victim-corp")] is victim_pool)

# (3) loop stall: durable ctor sleeping 0.2s on loop thread before guards
@Injectable(scope="durable")
class SlowPool:
    def __init__(self) -> None:
        time.sleep(0.2); self.thread = threading.current_thread().name
    @classmethod
    def get_durable_context_key(cls, request):
        return request.headers.get("x-tenant") if request else None

@Controller("/t", scope=Scope.REQUEST)
class T:
    def __init__(self, pool: SlowPool) -> None: self.pool = pool
    @Get("/")
    @Auth("bearer")
    def g(self) -> dict: return {"thread": self.pool.thread}

@Controller("/ping")
class Ping:
    @Get("/")
    async def g(self) -> dict: return {"ok": True}

@Module(controllers=[T, Ping], providers=[SlowPool, {"provide": AUTHENTICATOR_REGISTRY, "use_value": {}}])
class M3:
    pass
app3 = create_app(M3)
with TestClient(cast(Any, app3), raise_server_exceptions=False) as c:
    for _ in range(3): c.get("/ping/")
    base = []
    for _ in range(5):
        t0 = time.perf_counter(); c.get("/ping/"); base.append(time.perf_counter() - t0)
    lat = []; codes = []
    def attacker(i): codes.append(c.get("/t/", headers={"x-tenant": f"t{i}"}).status_code)
    def pinger():
        for _ in range(10):
            t0 = time.perf_counter(); c.get("/ping/"); lat.append(time.perf_counter() - t0)
    ths = [threading.Thread(target=attacker, args=(i,)) for i in range(5)] + [threading.Thread(target=pinger)]
    t0 = time.perf_counter(); [t.start() for t in ths]; [t.join() for t in ths]
    print("(3) attacker codes:", codes, "wall:", round(time.perf_counter() - t0, 2), "s; baseline /ping max:", round(max(base), 4),
          "s; /ping max during 5 anonymous durable ctors:", round(max(lat), 3), "s")
    r = c.get("/t/", headers={"x-tenant": "t0"})
    print("    ctor thread for partition t0 (via a guard-failing request):", app3.container.scope_manager.durable_instances[(M3, SlowPool, "t0")].thread)
    results["loop_stall"] = max(lat) > 0.15 and all(code == 403 for code in codes)

print("results:", results)
print("CONFIRMED" if all(results.values()) else "REFUTED/PARTIAL", results)
