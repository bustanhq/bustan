# ruff: noqa
# Evidence script for finding RF-06 (workflow id F-17) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-17: APPLICATION token unavailable during lifespan startup (eager singleton instantiation)."""
from __future__ import annotations

from typing import Annotated, Any, cast

import anyio
from starlette.testclient import TestClient

from bustan import APPLICATION, Controller, Get, Inject, Injectable, Module, create_app, create_app_context
from bustan.errors import LifecycleError, ProviderResolutionError


@Injectable  # default SINGLETON
class NeedsApp:
    def __init__(self, application: Annotated[object, Inject(APPLICATION)]) -> None:
        self.application = application


@Controller("/x")
class XController:
    def __init__(self, svc: NeedsApp) -> None:
        self.svc = svc

    @Get("/")
    def get(self) -> dict[str, str]:
        return {"app_type": type(self.svc.application).__name__}


@Module(providers=[NeedsApp], controllers=[XController], exports=[NeedsApp])
class AppModule:
    pass


results: dict[str, object] = {}


async def ctx_case() -> None:
    ctx = create_app_context(AppModule)
    svc = ctx.get(NeedsApp)
    results["lazy_ctx_get"] = type(svc.application).__name__
    print("[1] ApplicationContext.get(NeedsApp) before init -> OK, application is", results["lazy_ctx_get"])

    ctx2 = create_app_context(AppModule)
    try:
        await ctx2.init()
        results["init"] = "ok"
        print("[2] ctx.init() on fresh context -> OK")
    except LifecycleError as exc:
        results["init"] = f"LifecycleError: {exc}"
        print("[2] ctx.init() raised LifecycleError:", exc)
    except ProviderResolutionError as exc:
        results["init"] = f"ProviderResolutionError: {exc}"
        print("[2] ctx.init() raised RAW ProviderResolutionError (not LifecycleError):", exc)


anyio.run(ctx_case)

app = create_app(AppModule)
try:
    with TestClient(cast(Any, app)) as client:
        results["lifespan"] = "ok"
        print("[3] TestClient with lifespan -> startup OK, GET /x/ ->", client.get("/x/").json())
except Exception as exc:  # noqa: BLE001
    results["lifespan"] = f"{type(exc).__name__}: {exc}"
    print("[3] TestClient with lifespan -> startup FAILED:", type(exc).__name__, exc)

app2 = create_app(AppModule)
client = TestClient(cast(Any, app2))  # no context manager -> no lifespan
resp = client.get("/x/")
results["no_lifespan_request"] = (resp.status_code, resp.json() if resp.status_code == 200 else resp.text)
print("[4] No lifespan, lazy resolution inside request ->", results["no_lifespan_request"])

init_failed = str(results["init"]).startswith("ProviderResolutionError")
lifespan_failed = results["lifespan"] != "ok"
lazy_ok = results["no_lifespan_request"][0] == 200

confirmed = init_failed and lifespan_failed and lazy_ok
print()
print("init() failed with raw ProviderResolutionError:", init_failed)
print("lifespan startup failed:", lifespan_failed)
print("lazy resolution (ctx.get / request without lifespan) succeeded:", lazy_ok)
print("F-17", "CONFIRMED" if confirmed else "REFUTED")
