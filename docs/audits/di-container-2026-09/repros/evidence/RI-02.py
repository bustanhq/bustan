# ruff: noqa
# Evidence script for finding RI-02 (workflow id F-04) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-04: dict provider normalization drops scope."""
from typing import Any, cast
from starlette.requests import Request
from starlette.testclient import TestClient
from bustan import Controller, Get, Injectable, Module, Scope, create_app
from bustan.kernel.ioc.registry import normalize_provider
from bustan.kernel.module.graph import build_module_graph

results: dict[str, Any] = {}


@Injectable(scope="request")
class RequestAudit:
    def __init__(self) -> None:
        self.events: list[str] = []


AUDIT = object()

b = normalize_provider({"provide": AUDIT, "use_class": RequestAudit}, cast(Any, object()))
print("use_class dict binding scope:", b.scope.value, "(class declares", getattr(RequestAudit, "__bustan_provider__", None) or [v for k, v in vars(RequestAudit).items() if isinstance(v, dict)][0]["scope"].value, ")")
results["use_class_drops_class_scope"] = b.scope is Scope.SINGLETON

bv = normalize_provider({"provide": AUDIT, "use_value": 1, "scope": Scope.REQUEST}, cast(Any, object()))
print("use_value with scope=request ->", bv.scope.value)
results["use_value_ignores_scope"] = bv.scope is Scope.SINGLETON

be = normalize_provider({"provide": AUDIT, "use_existing": RequestAudit, "scope": Scope.SINGLETON}, cast(Any, object()))
print("use_existing with scope=singleton ->", be.scope.value)
results["use_existing_ignores_scope"] = be.scope is Scope.TRANSIENT

try:
    normalize_provider({"provide": AUDIT, "use_class": RequestAudit, "scope": "bogus"}, cast(Any, object()))
    results["invalid_scope_error"] = "none"
except Exception as exc:
    results["invalid_scope_error"] = type(exc).__name__
    print("invalid scope string raises:", type(exc).__module__ + "." + type(exc).__name__, exc)

# HTTP leak
from typing import Annotated
from bustan import Inject


@Controller("/audit", scope=Scope.REQUEST)
class AuditController:
    def __init__(self, audit: Annotated[RequestAudit, Inject(AUDIT)], request: Request) -> None:
        self.audit = audit
        self.audit.events.append("secret-of-" + request.headers.get("x-user-id", "anon"))

    @Get("/")
    def read(self) -> dict[str, Any]:
        return {"events": list(self.audit.events), "audit_id": id(self.audit)}


@Module(controllers=[AuditController], providers=[{"provide": AUDIT, "use_class": RequestAudit}])
class AppModule:
    pass


with TestClient(cast(Any, create_app(AppModule))) as client:
    a = client.get("/audit", headers={"x-user-id": "alice"})
    bb = client.get("/audit", headers={"x-user-id": "bob"})
    print("alice ->", a.json())
    print("bob   ->", bb.json())
    results["http_leak"] = "secret-of-alice" in bb.json()["events"] and a.json()["audit_id"] == bb.json()["audit_id"]

# Control: bare class entry honors the scope
with TestClient(cast(Any, create_app(type("AppCtl", (), {})))) if False else open("/dev/null") as _:
    pass


@Controller("/audit2", scope=Scope.REQUEST)
class AuditController2:
    def __init__(self, audit: RequestAudit, request: Request) -> None:
        self.audit = audit
        self.audit.events.append("secret-of-" + request.headers.get("x-user-id", "anon"))

    @Get("/")
    def read(self) -> dict[str, Any]:
        return {"events": list(self.audit.events)}


@Module(controllers=[AuditController2], providers=[RequestAudit])
class AppModule2:
    pass


with TestClient(cast(Any, create_app(AppModule2))) as client:
    client.get("/audit2", headers={"x-user-id": "alice"})
    bb = client.get("/audit2", headers={"x-user-id": "bob"})
    print("control (bare class) bob ->", bb.json())
    results["control_bare_class_isolated"] = bb.json()["events"] == ["secret-of-bob"]

print("RESULTS:", results)
print("F-04", "CONFIRMED" if results["use_class_drops_class_scope"] and results["http_leak"] else "REFUTED")
