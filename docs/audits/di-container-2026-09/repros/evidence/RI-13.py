# ruff: noqa
# Evidence script for finding RI-13 (workflow id F-74) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-74: route middleware runs outside request-scope lifetime; request-scoped middleware cannot inject Response."""
import logging
from typing import Any, cast
from starlette.requests import Request
from starlette.responses import Response
from starlette.testclient import TestClient
from bustan import Controller, Get, Injectable, Module, Scope, create_app
from bustan.pipeline.middleware import Middleware, MiddlewareConsumer
logging.basicConfig(level=logging.CRITICAL)

BUILT: list[str] = []

@Injectable(scope="request")
class Ident:
    def __init__(self, request: Request) -> None:
        self.user = request.headers.get("x-user"); self.events: list[str] = []
        BUILT.append(f"Ident({self.user})#{id(self)}")

@Injectable(scope="request")
class Mw(Middleware):
    def __init__(self, ident: Ident) -> None: self.ident = ident
    async def use(self, request, call_next):
        resp = await call_next(request)
        again = request.app.state.bustan_container.resolve(
            Ident, module=request.app.state.bustan_module_graph.root_key, request=request)
        resp.headers["x-same-ident"] = str(again is self.ident)
        resp.headers["x-audit-events"] = str(len(again.events))
        return resp

@Injectable(scope="request")
class MwWithResponse(Middleware):
    def __init__(self, ident: Ident, response: Response) -> None: self.ident = ident
    async def use(self, request, call_next): return await call_next(request)

@Controller("/c", scope=Scope.REQUEST)
class Cc:
    def __init__(self, ident: Ident) -> None: self.ident = ident
    @Get("/")
    def g(self) -> dict:
        self.ident.events.append("handled")
        return {"user": self.ident.user, "same_as_middleware": None}

@Controller("/d", scope=Scope.REQUEST)
class Dd:
    @Get("/")
    def g(self) -> dict: return {}

@Module(controllers=[Cc, Dd], providers=[Ident, Mw, MwWithResponse])
class M:
    def configure(self, consumer: MiddlewareConsumer) -> None:
        consumer.apply(Mw).for_routes(Cc)
        consumer.apply(MwWithResponse).for_routes(Dd)

app = create_app(M)
ok = {}
with TestClient(cast(Any, app), raise_server_exceptions=False) as client:
    r = client.get("/c/", headers={"x-user": "u2"})
    print("(a) /c:", r.status_code, r.json(), "x-same-ident:", r.headers.get("x-same-ident"),
          "audit events visible after call_next:", r.headers.get("x-audit-events"))
    print("    Ident constructions during one request:", BUILT)
    ok["second_instance"] = r.headers.get("x-same-ident") == "False" and len(BUILT) == 2 and r.headers.get("x-audit-events") == "0"
    BUILT.clear()
    r = client.get("/d/")
    print("(b) /d with request-scoped middleware injecting Response:", r.status_code, r.text[:160])
    ok["response_500"] = r.status_code == 500
print("CONFIRMED" if all(ok.values()) else "REFUTED/PARTIAL", ok)
