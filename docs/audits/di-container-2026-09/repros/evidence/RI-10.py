# ruff: noqa
# Evidence script for finding RI-10 (workflow id F-71) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-71: @Controller(scope=Scope.DURABLE) accepted but served as an app-wide singleton."""
import logging
from typing import Any, cast
from starlette.testclient import TestClient
from bustan import Controller, Get, Module, Scope, create_app
from bustan.platform.http.metadata import get_controller_metadata
from bustan.core.errors import RouteDefinitionError
logging.basicConfig(level=logging.CRITICAL)

try:
    @Controller("/d", scope=Scope.DURABLE)
    class DC:
        n = 0
        def __init__(self) -> None:
            DC.n += 1
            self.id = DC.n
        @Get("/")
        def read(self) -> dict:
            return {"controller_instance": self.id}
    print("decorator accepted durable scope:", get_controller_metadata(DC).scope)
except Exception as exc:
    print("REFUTED: decorator rejected durable scope:", type(exc).__name__, exc)
    raise SystemExit(0)

@Module(controllers=[DC])
class AppModule:
    pass

app = create_app(AppModule)
ids = []
with TestClient(cast(Any, app)) as client:
    for tenant in ("a", "b", "a"):
        r = client.get("/d", headers={"x-tenant": tenant})
        ids.append(r.json()["controller_instance"])
        print("tenant", tenant, "->", r.status_code, r.json())
sm = app.container.scope_manager
print("controller_singletons:", [(k[1].__name__) for k in sm.controller_singletons])
print("durable_instances:", list(sm.durable_instances))

# Also: can a controller carry get_durable_context_key at all?
try:
    @Controller("/e", scope=Scope.DURABLE)
    class EC:
        @classmethod
        def get_durable_context_key(cls, request):
            return request.headers.get("x-tenant") if request else None
        @Get("/")
        def read(self) -> dict:
            return {}
    @Module(controllers=[EC])
    class M2:
        pass
    app2 = create_app(M2)
    with TestClient(cast(Any, app2)) as c2:
        c2.get("/e")
    print("controller with public get_durable_context_key: accepted by scanner")
except RouteDefinitionError as exc:
    print("controller with public get_durable_context_key: scanner rejected ->", exc)

if ids == [1, 1, 1] and (AppModule, DC) in sm.controller_singletons and not sm.durable_instances:
    print("CONFIRMED: durable controller built once and shared across tenants a/b as a controller singleton")
else:
    print("REFUTED: ids", ids)
