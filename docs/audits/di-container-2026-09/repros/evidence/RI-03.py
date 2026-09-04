# ruff: noqa
# Evidence script for finding RI-03 (workflow id F-02) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-02: singleton provider / singleton controller capturing a tenant-keyed DURABLE instance."""
from typing import Any, cast
from starlette.requests import Request
from starlette.testclient import TestClient
from bustan import Controller, Get, Injectable, Module, Scope, create_app
from bustan.app.bootstrap import _create_app


def make_durable():
    @Injectable(scope=Scope.DURABLE)
    class TenantConfig:
        def __init__(self) -> None:
            self.tenant = "unset"

        @classmethod
        def get_durable_context_key(cls, request: Request | None) -> str:
            if request is None:
                return "<no-request>"
            return request.headers.get("x-tenant-id", "none")

    return TenantConfig


results: dict[str, bool] = {}

# Variant A: singleton controller depends on durable provider (with lifespan)
TenantConfigA = make_durable()


@Controller("/cfg")
class CfgController:
    def __init__(self, cfg: TenantConfigA, request: Request) -> None:  # type: ignore[valid-type]
        cfg.tenant = request.headers.get("x-tenant-id", "none")  # record who built it
        self.cfg = cfg

    @Get("/")
    def read(self) -> dict[str, Any]:
        return {"tenant": self.cfg.tenant, "cfg_id": id(self.cfg)}


@Module(controllers=[CfgController], providers=[TenantConfigA])
class AppA:
    pass


with TestClient(cast(Any, create_app(AppA))) as client:
    a = client.get("/cfg", headers={"x-tenant-id": "tenant-a"})
    b = client.get("/cfg", headers={"x-tenant-id": "tenant-b"})
    print("[A controller] tenant-a ->", a.json())
    print("[A controller] tenant-b ->", b.json())
    results["controller"] = b.json()["tenant"] == "tenant-a" and a.json()["cfg_id"] == b.json()["cfg_id"]

# Variant B: singleton provider depends on durable provider (no lifespan -> first request builds it)
TenantConfigB = make_durable()


@Injectable()
class ReportService:
    def __init__(self, cfg: TenantConfigB) -> None:  # type: ignore[valid-type]
        self.cfg = cfg


@Controller("/report", scope=Scope.REQUEST)
class ReportController:
    def __init__(self, svc: ReportService, request: Request) -> None:
        if svc.cfg.tenant == "unset":
            svc.cfg.tenant = request.headers.get("x-tenant-id", "none")
        self.svc = svc

    @Get("/")
    def read(self) -> dict[str, Any]:
        return {"tenant": self.svc.cfg.tenant, "cfg_id": id(self.svc.cfg)}


@Module(controllers=[ReportController], providers=[ReportService, TenantConfigB])
class AppB:
    pass


with TestClient(cast(Any, _create_app(AppB, no_lifespan=True))) as client:
    a = client.get("/report", headers={"x-tenant-id": "tenant-a"})
    b = client.get("/report", headers={"x-tenant-id": "tenant-b"})
    print("[B provider, no lifespan] tenant-a ->", a.json())
    print("[B provider, no lifespan] tenant-b ->", b.json())
    results["provider_nolifespan"] = b.json()["tenant"] == "tenant-a" and a.json()["cfg_id"] == b.json()["cfg_id"]

# Variant C: singleton provider depends on durable provider, WITH lifespan (eager startup, request None)
from bustan.core.ioc.container import build_container
from bustan.core.module.graph import build_module_graph

with TestClient(cast(Any, create_app(AppB))) as client:
    a = client.get("/report", headers={"x-tenant-id": "tenant-a"})
    b = client.get("/report", headers={"x-tenant-id": "tenant-b"})
    print("[C provider, lifespan] tenant-a ->", a.json())
    print("[C provider, lifespan] tenant-b ->", b.json())
    results["provider_lifespan_shared"] = a.json()["cfg_id"] == b.json()["cfg_id"]
    app_ctx = getattr(client.app, "state", None)
# inspect partition key used at startup
container = build_container(build_module_graph(AppB))
container.resolve(ReportService, module=AppB)
print("[C] durable partitions after eager singleton resolve:", [k[2] for k in container.scope_manager.durable_instances])
results["startup_partition_is_no_request"] = any(k[2] == "<no-request>" for k in container.scope_manager.durable_instances)

# Variant D: durable provider that also injects Request, singleton depends on it, eager startup
@Injectable(scope=Scope.DURABLE)
class TenantCtx:
    def __init__(self, request: Request) -> None:
        self.request = request

    @classmethod
    def get_durable_context_key(cls, request: Request | None) -> str:
        return request.headers.get("x-tenant-id", "none") if request is not None else "<no-request>"


@Injectable()
class NeedsCtx:
    def __init__(self, ctx: TenantCtx) -> None:
        self.ctx = ctx


@Module(providers=[TenantCtx, NeedsCtx])
class AppD:
    pass


try:
    with TestClient(cast(Any, create_app(AppD))):
        print("[D] startup succeeded (unexpected)")
        results["startup_error_hides_design"] = False
except Exception as exc:
    print("[D] startup error type:", type(exc).__name__, "msg:", str(exc)[:200])
    results["startup_error_hides_design"] = "Request" in str(exc) and "durable" not in str(exc).lower()

print("RESULTS:", results)
core = results["controller"] and results["provider_nolifespan"]
print("F-02", "CONFIRMED" if core else "REFUTED")
