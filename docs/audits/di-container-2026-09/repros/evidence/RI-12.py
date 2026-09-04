# ruff: noqa
# Evidence script for finding RI-12 (workflow id F-73) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-73: request_context_id is id(request)-based and collides across sequential requests."""
import gc, logging
from typing import Any, cast
from starlette.requests import Request
from starlette.testclient import TestClient
from bustan import Controller, Get, Injectable, Module, Scope, create_app, request_context_id
logging.basicConfig(level=logging.CRITICAL)

SEEN: dict[str, list[str]] = {}

@Injectable(scope="request")
class Ident:
    def __init__(self, request: Request) -> None:
        self.cid = request_context_id(request).value
        self.user = request.headers.get("x-user")

@Controller("/c", scope=Scope.REQUEST)
class C:
    def __init__(self, ident: Ident) -> None: self.ident = ident
    @Get("/")
    def get(self) -> dict:
        SEEN.setdefault(self.ident.cid, []).append(self.ident.user)
        return {"cid": self.ident.cid}

@Module(controllers=[C], providers=[Ident])
class M: pass

app = create_app(M)
with TestClient(cast(Any, app)) as client:
    for i in range(200):
        client.get("/c/", headers={"x-user": f"user-{i}"})
collisions = {k: v for k, v in SEEN.items() if len(set(v)) > 1}
print("distinct context ids:", len(SEEN), "of 200 requests; ids handed to more than one distinct user:", len(collisions))
print("sample:", list(collisions.items())[:2])
if collisions:
    print("CONFIRMED: request_context_id values are reused across different sequential requests/users")
else:
    print("REFUTED: no id reuse observed")
