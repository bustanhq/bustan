# ruff: noqa
# Evidence script for finding RI-14 (workflow id F-75) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-75: transient provider injecting Request under a REQUEST-scoped controller -> 500?"""
import logging
from typing import Any, cast
from starlette.requests import Request
from starlette.testclient import TestClient
from bustan import Controller, Get, Injectable, Module, Scope, create_app
from bustan.kernel.errors import ProviderResolutionError

logging.basicConfig(level=logging.CRITICAL)

@Injectable(scope="transient")
class Helper:
    def __init__(self, request: Request) -> None:
        self.path = request.url.path

@Controller("/t", scope=Scope.REQUEST)
class T:
    def __init__(self, helper: Helper) -> None:
        self.helper = helper
    @Get("/")
    def g(self) -> dict:
        return {"path": self.helper.path}

@Module(controllers=[T], providers=[Helper])
class M:
    pass

# 1) bootstrap does not detect it
try:
    app = create_app(M)
    print("bootstrap: create_app succeeded (no bootstrap-time detection)")
except Exception as exc:
    print("bootstrap: create_app raised", type(exc).__name__, exc)
    raise SystemExit(0)

# 2) request-time behaviour
with TestClient(cast(Any, app), raise_server_exceptions=False) as client:
    r = client.get("/t/")
    print("GET /t/ ->", r.status_code, r.text[:120])

# 3) the underlying resolver error, resolved with an active request
from starlette.requests import Request as _R
scope = {"type": "http", "method": "GET", "path": "/t/", "headers": [], "query_string": b"", "app": app}
req = _R(scope)
try:
    app.container.instantiate_class(T, module=app.root_key, request=req)
    print("direct instantiate: succeeded (unexpected)")
    direct_error = None
except ProviderResolutionError as exc:
    direct_error = str(exc)
    print("direct instantiate: ProviderResolutionError:", direct_error[:300])

# 4) control: same helper marked request-scoped works
@Injectable(scope="request")
class Helper2:
    def __init__(self, request: Request) -> None:
        self.path = request.url.path
@Controller("/u", scope=Scope.REQUEST)
class U:
    def __init__(self, helper: Helper2) -> None:
        self.helper = helper
    @Get("/")
    def g(self) -> dict:
        return {"path": self.helper.path}
@Module(controllers=[U], providers=[Helper2])
class M2:
    pass
with TestClient(cast(Any, create_app(M2)), raise_server_exceptions=False) as client:
    r2 = client.get("/u/")
    print("control (request-scoped helper) GET /u/ ->", r2.status_code, r2.text[:80])

ok = r.status_code == 500 and direct_error is not None and "framework-owned type Request" in direct_error and r2.status_code == 200
print("RESULT:", "CONFIRMED - transient helper with Request under request-scoped controller gives 500 at first request, not detected at bootstrap" if ok else "REFUTED - behaviour differs from description")
