# ruff: noqa
# Evidence script for finding EX-04 (workflow id F-82) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-82: 403 problem-details bodies disclose the guard class module path and auth strategy names."""
from __future__ import annotations

import logging
from typing import Any, cast

from starlette.testclient import TestClient

from bustan import Controller, Get, Guard, Module, UseGuards, create_app
from bustan.security.policy import Auth

logging.basicConfig(level=logging.CRITICAL)


class InternalOnlyGuard(Guard):
    def can_activate(self, context):
        return False


@Controller("/x")
class X:
    @Get("/deny")
    @UseGuards(InternalOnlyGuard)
    def deny(self) -> dict:
        return {}

    @Get("/auth")
    @Auth("acme-hmac-v2")
    def auth(self) -> dict:
        return {}


@Module(controllers=[X])
class M:
    pass


results: list[bool] = []
for debug in (False, True):
    app = create_app(M, debug=debug)
    with TestClient(cast(Any, app), raise_server_exceptions=False) as client:
        r = client.get("/x/deny")
        body = r.json()
        print(f"debug={debug} GET /x/deny -> {r.status_code} {body}")
        results.append(r.status_code == 403 and body.get("detail") == f"Guard {InternalOnlyGuard.__module__}.InternalOnlyGuard blocked the request")
        r = client.get("/x/auth")
        body = r.json()
        print(f"debug={debug} GET /x/auth  -> {r.status_code} {body}")
        results.append(r.status_code == 403 and "acme-hmac-v2" in body.get("detail", ""))

if all(results):
    print("RESULT: CONFIRMED - 403 detail contains guard module path + qualname, and the auth strategy name, with debug=False and debug=True")
else:
    print("RESULT: REFUTED/UNEXPECTED - results", results)
