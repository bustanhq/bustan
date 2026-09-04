# ruff: noqa
# Evidence script for finding OL-02 (workflow id F-15) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-15: APP_* global pipeline providers are resolved eagerly at compile time: overrides are a silent no-op,
only one per module allowed, request-scoped or async-factory-dependent guards fail at create_app."""
from __future__ import annotations

from typing import Any, cast

from starlette.testclient import TestClient

from bustan import APP_GUARD, Controller, Get, Guard, Injectable, Module, create_app
from bustan.core.errors import InvalidModuleError, ProviderResolutionError
from bustan.pipeline.context import ExecutionContext
from bustan.testing import create_test_app, override_provider


@Injectable
class DenyAll(Guard):
    def can_activate(self, context: ExecutionContext) -> bool:
        return False


class AllowAll(Guard):
    def can_activate(self, context: ExecutionContext) -> bool:
        return True


@Controller("/secure")
class SecureController:
    @Get("/")
    def get(self) -> dict[str, str]:
        return {"ok": "yes"}


@Module(controllers=[SecureController], providers=[{"provide": APP_GUARD, "use_class": DenyAll}])
class AppModule:
    pass


checks: dict[str, bool] = {}

print("-- 1. create_test_app(provider_overrides={APP_GUARD: AllowAll()})")
app = create_test_app(AppModule, provider_overrides={APP_GUARD: AllowAll()})
has = app.container.has_override(APP_GUARD)
with TestClient(cast(Any, app)) as client:
    status1 = client.get("/secure/").status_code
print("   has_override(APP_GUARD):", has, "| GET /secure/ ->", status1)
checks["create_test_app_override_ignored"] = has and status1 == 403

print("-- 2. override_provider(app, APP_GUARD, AllowAll()) at runtime")
app2 = create_app(AppModule)
with TestClient(cast(Any, app2)) as client:
    with override_provider(app2, APP_GUARD, AllowAll()):
        status2 = client.get("/secure/").status_code
print("   GET /secure/ inside override ->", status2)
checks["override_provider_ignored"] = status2 == 403

print("-- 2b. control: a guard override applied BEFORE create_app via a test module works")

@Module(controllers=[SecureController], providers=[{"provide": APP_GUARD, "use_value": AllowAll()}])
class AllowModule:
    pass

with TestClient(cast(Any, create_app(AllowModule))) as client:
    status_ctl = client.get("/secure/").status_code
print("   GET /secure/ with AllowAll declared in module ->", status_ctl)
checks["control_allow_module_200"] = status_ctl == 200

print("-- 3. two APP_GUARD entries in one module")
try:
    @Module(
        controllers=[SecureController],
        providers=[
            {"provide": APP_GUARD, "use_class": DenyAll},
            {"provide": APP_GUARD, "use_value": AllowAll()},
        ],
    )
    class TwoGuards:
        pass

    create_app(TwoGuards)
    print("   accepted two APP_GUARD entries")
    checks["duplicate_rejected"] = False
except InvalidModuleError as exc:
    print("   InvalidModuleError:", exc)
    checks["duplicate_rejected"] = True

print("-- 4. request-scoped APP_GUARD")
try:
    @Module(
        controllers=[SecureController],
        providers=[{"provide": APP_GUARD, "use_class": DenyAll, "scope": "request"}],
    )
    class ReqGuard:
        pass

    create_app(ReqGuard)
    print("   create_app accepted request-scoped APP_GUARD")
    checks["request_scoped_fails_at_create_app"] = False
except ProviderResolutionError as exc:
    print("   ProviderResolutionError:", exc)
    checks["request_scoped_fails_at_create_app"] = "requires an active request" in str(exc)

print("-- 5. APP_GUARD depending on an async-factory singleton")

async def build_conn() -> str:
    return "conn"


from typing import Annotated
from bustan import Inject


@Injectable
class ConnGuard(Guard):
    def __init__(self, conn: Annotated[str, Inject("CONN")]) -> None:
        self.conn = conn

    def can_activate(self, context: ExecutionContext) -> bool:
        return True


try:
    @Module(
        controllers=[SecureController],
        providers=[
            {"provide": "CONN", "use_factory": build_conn},
            {"provide": APP_GUARD, "use_class": ConnGuard},
        ],
    )
    class AsyncDepGuard:
        pass

    create_app(AsyncDepGuard)
    print("   create_app accepted APP_GUARD with async-factory dependency")
    checks["async_dep_fails_at_create_app"] = False
except ProviderResolutionError as exc:
    print("   ProviderResolutionError:", exc)
    checks["async_dep_fails_at_create_app"] = "Initialize the application before resolving it synchronously" in str(exc)

print()
for k, v in checks.items():
    print(f"   {k}: {v}")
confirmed = all(checks.values())
print("F-15", "CONFIRMED" if confirmed else "REFUTED")
