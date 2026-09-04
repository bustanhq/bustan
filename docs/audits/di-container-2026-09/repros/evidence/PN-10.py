# ruff: noqa
# Evidence script for finding PN-10 (workflow id F-89) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
# F-89: durable scope accepts non-class targets (use_factory / use_value) at
# registration but can never resolve them; an instance-method
# get_durable_context_key is invoked unbound and leaks a raw TypeError.
from typing import Any, cast

from starlette.requests import Request
from starlette.testclient import TestClient

from bustan import Controller, Get, Injectable, Module, Scope, create_app
from bustan.core.errors import ProviderResolutionError
from bustan.common.types import ProviderScope

TENANT_CACHE = object()
VALUE_TOKEN = object()


def make_cache():
    return {"tenant": "?"}


def mk_request(tenant: bytes = b"a") -> Request:
    return Request({
        "type": "http", "method": "GET", "path": "/",
        "headers": [(b"x-tenant", tenant)], "query_string": b"", "state": {},
    })


results: dict[str, str] = {}

# --- part 1: use_factory + scope durable ---------------------------------
@Module(providers=[{"provide": TENANT_CACHE, "use_factory": make_cache, "scope": "durable"}])
class FactoryDurableModule:
    pass


app = create_app(FactoryDurableModule)
binding = app.container.registry.bindings[(FactoryDurableModule, TENANT_CACHE)]
print("[factory] registration accepted; binding.scope =", binding.scope, "target =", type(binding.target).__name__)
try:
    app.container.resolve(TENANT_CACHE, module=FactoryDurableModule, request=mk_request())
    results["factory"] = "resolved"
except ProviderResolutionError as exc:
    results["factory"] = "ProviderResolutionError"
    print("[factory] resolve ->", type(exc).__name__ + ":", str(exc)[:160])
except Exception as exc:  # noqa: BLE001
    results["factory"] = "RAW " + type(exc).__name__
    print("[factory] resolve -> RAW", type(exc).__name__, str(exc)[:160])

# --- part 1b: use_value + scope durable (normalize_provider forces SINGLETON) --
@Module(providers=[{"provide": VALUE_TOKEN, "use_value": {"v": 1}, "scope": "durable"}])
class ValueDurableModule:
    pass


app_v = create_app(ValueDurableModule)
vb = app_v.container.registry.bindings[(ValueDurableModule, VALUE_TOKEN)]
print("[value] registration accepted; requested scope 'durable', binding.scope =", vb.scope)
results["value_scope"] = str(vb.scope)

# --- part 2: instance-method get_durable_context_key --------------------
@Injectable(scope=Scope.DURABLE)
class TenantStore:
    def get_durable_context_key(self, request: Request | None):  # missing @classmethod
        return request.headers.get("x-tenant") if request is not None else None


@Controller("/")
class Ctl:
    def __init__(self, store: TenantStore) -> None:
        self.store = store

    @Get("/")
    def index(self) -> dict[str, str]:
        return {"ok": "1"}


@Module(providers=[TenantStore], controllers=[Ctl])
class InstanceMethodModule:
    pass


app2 = create_app(InstanceMethodModule)
try:
    app2.container.resolve(TenantStore, module=InstanceMethodModule, request=mk_request())
    results["instance_method"] = "resolved"
except ProviderResolutionError as exc:
    results["instance_method"] = "ProviderResolutionError"
    print("[instance-method] resolve ->", type(exc).__name__ + ":", str(exc)[:160])
except Exception as exc:  # noqa: BLE001
    results["instance_method"] = "RAW " + type(exc).__name__
    print("[instance-method] resolve -> RAW", type(exc).__name__ + ":", str(exc)[:160])

with TestClient(cast(Any, app2), raise_server_exceptions=False) as client:
    r = client.get("/")
print("[instance-method] over HTTP ->", r.status_code, r.text[:100])
results["http"] = str(r.status_code)

# --- part 3: a correctly written classmethod works (control) ------------
@Injectable(scope=Scope.DURABLE)
class GoodStore:
    @classmethod
    def get_durable_context_key(cls, request: Request | None):
        return request.headers.get("x-tenant") if request is not None else None


@Module(providers=[GoodStore])
class GoodModule:
    pass


app3 = create_app(GoodModule)
a = app3.container.resolve(GoodStore, module=GoodModule, request=mk_request(b"a"))
a2 = app3.container.resolve(GoodStore, module=GoodModule, request=mk_request(b"a"))
b = app3.container.resolve(GoodStore, module=GoodModule, request=mk_request(b"b"))
print("[control] classmethod hook: same tenant cached =", a is a2, "; different tenant distinct =", a is not b)

ok = (
    results["factory"] == "ProviderResolutionError"
    and results["instance_method"].startswith("RAW TypeError")
    and results["http"] == "500"
    and a is a2 and a is not b
)
print("RESULT:", "PASS (defect reproduced)" if ok else "FAIL (defect not reproduced)", results)
