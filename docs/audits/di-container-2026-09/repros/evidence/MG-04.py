# ruff: noqa
# Evidence script for finding MG-04 (workflow id F-25) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-25: unresolvable deps of transient/request providers and controllers are not validated at bootstrap."""
import asyncio
from bustan import Controller, Get, Injectable, Module, create_app, create_app_context
from bustan.common.types import ProviderScope
from starlette.testclient import TestClient


class NotRegistered:
    pass


@Injectable(scope=ProviderScope.TRANSIENT)
class TransientNeedsMissing:
    def __init__(self, dep: NotRegistered) -> None:
        self.dep = dep


@Injectable(scope=ProviderScope.REQUEST)
class RequestNeedsMissing:
    def __init__(self, dep: NotRegistered) -> None:
        self.dep = dep


@Injectable
class SingletonNeedsMissing:
    def __init__(self, dep: NotRegistered) -> None:
        self.dep = dep


@Controller("/t")
class TController:
    def __init__(self, svc: TransientNeedsMissing) -> None:
        self.svc = svc

    @Get("/")
    def get(self) -> dict:
        return {}


@Controller("/r")
class RController:
    def __init__(self, svc: RequestNeedsMissing) -> None:
        self.svc = svc

    @Get("/")
    def get(self) -> dict:
        return {}


@Controller("/c")
class CController:
    def __init__(self, dep: NotRegistered) -> None:
        self.dep = dep

    @Get("/")
    def get(self) -> dict:
        return {}


@Controller("/ok")
class OkController:
    @Get("/")
    def get(self) -> dict:
        return {"ok": True}


@Module(
    providers=[TransientNeedsMissing, RequestNeedsMissing],
    controllers=[TController, RController, CController, OkController],
)
class AppModule:
    pass


results = {}
try:
    app = create_app(AppModule)
    print("create_app: succeeded (no validation error)")
except Exception as exc:
    print("create_app raised:", type(exc).__name__, exc)
    print("RESULT: REFUTED (bootstrap caught the problem)")
    raise SystemExit(0)

try:
    with TestClient(app, raise_server_exceptions=False) as client:
        print("lifespan startup: succeeded")
        for path in ("/ok/", "/t/", "/r/", "/c/"):
            r = client.get(path)
            results[path] = r.status_code
            print(path, "->", r.status_code, r.text[:140])
except Exception as exc:
    print("lifespan startup raised:", type(exc).__name__, exc)
    print("RESULT: REFUTED (lifespan caught the problem)")
    raise SystemExit(0)

print("---- control: singleton with missing dep ----")


@Module(providers=[SingletonNeedsMissing])
class AppModule2:
    pass


ctx = create_app_context(AppModule2)
try:
    asyncio.run(ctx.init())
    print("singleton control: startup passed (unexpected)")
    singleton_caught = False
except Exception as exc:
    print("singleton control: startup FAILED at init:", type(exc).__name__, str(exc)[:160])
    singleton_caught = True

ok = results.get("/ok/") == 200 and all(results.get(p) == 500 for p in ("/t/", "/r/", "/c/"))
if ok and singleton_caught:
    print("RESULT: CONFIRMED - create_app and lifespan pass; /t/ /r/ /c/ are 500 at first request while singleton case fails at startup")
else:
    print("RESULT: NOT CONFIRMED", results, singleton_caught)
