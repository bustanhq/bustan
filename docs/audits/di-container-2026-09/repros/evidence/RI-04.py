# ruff: noqa
# Evidence script for finding RI-04 (workflow id F-03) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-03: durable provider injects Request and retains the first caller's Request for the partition."""
from typing import Any, cast
from starlette.requests import Request
from starlette.testclient import TestClient
from bustan import Controller, Get, Injectable, Module, Scope, create_app
from bustan.kernel.errors import ProviderResolutionError
from bustan.kernel.ioc.container import build_container
from bustan.kernel.module.graph import build_module_graph

results: dict[str, Any] = {}


@Injectable(scope=Scope.DURABLE)
class TenantCtx:
    def __init__(self, request: Request) -> None:
        self.request = request
        self.first_user = request.headers.get("x-user", "?")

    @classmethod
    def get_durable_context_key(cls, request: Request | None) -> str:
        return request.headers.get("x-tenant-id", "none") if request is not None else "<no-request>"


@Controller("/t", scope=Scope.REQUEST)
class TCtl:
    def __init__(self, ctx: TenantCtx) -> None:
        self.ctx = ctx

    @Get("/")
    def read(self) -> dict[str, Any]:
        return {
            "first_user": self.ctx.first_user,
            "auth_in_retained_request": self.ctx.request.headers.get("authorization"),
            "request_id": id(self.ctx.request),
        }


@Module(controllers=[TCtl], providers=[TenantCtx])
class AppModule:
    pass


app = create_app(AppModule)
with TestClient(cast(Any, app)) as client:
    a = client.get("/t", headers={"x-tenant-id": "acme", "x-user": "alice", "authorization": "Bearer alice-token"})
    b = client.get("/t", headers={"x-tenant-id": "acme", "x-user": "bob", "authorization": "Bearer bob-token"})
    print("alice ->", a.json())
    print("bob   ->", b.json())
    results["request_retained_across_users"] = (
        b.json()["first_user"] == "alice" and b.json()["auth_in_retained_request"] == "Bearer alice-token"
    )
    # retention: 200 distinct tenants
    for i in range(200):
        client.get("/t", headers={"x-tenant-id": f"tenant-{i}", "authorization": f"Bearer tok-{i}"})

# count retained Request objects in the durable cache of the running app's container
container = None
for attr in ("container", "_container"):
    container = getattr(app, attr, None) or container
if container is None:
    st = getattr(app, "state", None)
    container = getattr(st, "container", None) if st is not None else None
if container is None:
    # walk app attributes for a ScopeManager
    from bustan.kernel.ioc.scopes import ScopeManager
    def find_sm(obj, depth=0, seen=None):
        seen = seen or set()
        if id(obj) in seen or depth > 4:
            return None
        seen.add(id(obj))
        if isinstance(obj, ScopeManager):
            return obj
        for v in list(getattr(obj, "__dict__", {}).values()):
            r = find_sm(v, depth + 1, seen)
            if r is not None:
                return r
        return None
    sm = find_sm(app)
else:
    sm = container.scope_manager
if sm is not None:
    retained = sum(1 for v in sm.durable_instances.values() if isinstance(getattr(v, "request", None), Request))
    print("durable partitions:", len(sm.durable_instances), "retained Request objects:", retained)
    results["requests_retained"] = retained
else:
    print("could not locate ScopeManager on app")

# Sub-claim: durable owner cannot depend on request-scoped provider (guard treats as non-request owner)
@Injectable(scope=Scope.REQUEST)
class ReqThing:
    pass


@Injectable(scope=Scope.DURABLE)
class DurNeedsReq:
    def __init__(self, r: ReqThing) -> None:
        self.r = r

    @classmethod
    def get_durable_context_key(cls, request: Request | None) -> str:
        return "k"


@Module(providers=[ReqThing, DurNeedsReq])
class M2:
    pass


from starlette.requests import Request as _R
def _req(headers=()):
    return _R({"type": "http", "method": "GET", "path": "/", "headers": list(headers), "query_string": b"", "scheme": "http", "server": ("t", 80), "client": ("c", 1)})

c = build_container(build_module_graph(M2))
try:
    c.resolve(DurNeedsReq, module=M2, request=_req())
    results["durable_cannot_depend_on_request_scoped"] = False
    print("durable -> request-scoped dep: allowed")
except ProviderResolutionError as exc:
    results["durable_cannot_depend_on_request_scoped"] = True
    print("durable -> request-scoped dep: REJECTED:", exc)

# Sub-claim: durable use_factory provider rejected
TOK = object()
@Module(providers=[{"provide": TOK, "use_factory": lambda: object(), "scope": Scope.DURABLE}])
class M3:
    pass
c3 = build_container(build_module_graph(M3))
try:
    c3.resolve(TOK, module=M3, request=_req())
    results["durable_factory_rejected"] = False
    print("durable use_factory: allowed")
except ProviderResolutionError as exc:
    results["durable_factory_rejected"] = True
    print("durable use_factory: REJECTED:", exc)

print("RESULTS:", results)
print("F-03", "CONFIRMED" if results["request_retained_across_users"] else "REFUTED")
