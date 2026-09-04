# ruff: noqa
# Evidence script for finding EX-02 (workflow id F-76) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-76: AUTHENTICATOR_REGISTRY wiring/runtime errors surface as 403 'Unknown authenticator registry' per request; no compile-time validation."""
import logging
from typing import Any, cast
from starlette.requests import Request
from starlette.testclient import TestClient
from bustan import Controller, Get, Injectable, Module, create_app
from bustan.pipeline.auth import AUTHENTICATOR_REGISTRY
from bustan.security.policy import Auth

logging.basicConfig(level=logging.CRITICAL)

class Ok:
    async def authenticate(self, context):
        class P:
            id = "a"; roles = (); permissions = ()
        return P()

@Controller("/p")
class P:
    @Get("/")
    @Auth("bearer")
    def g(self) -> dict:
        return {"ok": True}

results = {}

# control: correctly wired registry
@Module(controllers=[P], providers=[{"provide": AUTHENTICATOR_REGISTRY, "use_value": {"bearer": Ok()}}])
class App0: pass
with TestClient(cast(Any, create_app(App0)), raise_server_exceptions=False) as c:
    r = c.get("/p/", headers={"authorization": "Bearer x"})
    results["control"] = (r.status_code, r.json())
    print("control wired registry:", results["control"])

# (a) registry in AuthModule, not exported/imported into the controller module
@Module(providers=[{"provide": AUTHENTICATOR_REGISTRY, "use_value": {"bearer": Ok()}}])
class AuthModule: pass
@Module(controllers=[P], imports=[])
class App1: pass
try:
    app = create_app(App1)
    print("(a) create_app succeeded with registry not visible from controller module")
    with TestClient(cast(Any, app), raise_server_exceptions=False) as c:
        r = c.get("/p/", headers={"authorization": "Bearer x"})
        results["a"] = (r.status_code, r.json().get("detail"))
        print("(a) registry not visible:", results["a"])
        r = c.get("/p/", headers={"authorization": "Bearer x"})
        print("(a) second request:", r.status_code, r.json().get("detail"))
except Exception as exc:
    print("(a) create_app raised", type(exc).__name__, exc)

# (b) request-scoped async factory registry
async def make_registry():
    return {"bearer": Ok()}
@Module(controllers=[P], providers=[{"provide": AUTHENTICATOR_REGISTRY, "use_factory": make_registry, "scope": "request"}])
class App2: pass
try:
    app = create_app(App2)
    with TestClient(cast(Any, app), raise_server_exceptions=False) as c:
        r = c.get("/p/", headers={"authorization": "Bearer x"})
        results["b"] = (r.status_code, r.json().get("detail"))
        print("(b) async request-scoped registry:", results["b"])
except Exception as exc:
    print("(b) create_app raised", type(exc).__name__, exc)

# (c) registry class whose constructor raises KeyError
@Injectable(scope="request")
class Reg(dict):
    def __init__(self, request: Request) -> None:
        super().__init__()
        raise KeyError("db down")
@Module(controllers=[P], providers=[{"provide": AUTHENTICATOR_REGISTRY, "use_existing": Reg}, Reg])
class App3: pass
try:
    app = create_app(App3)
    with TestClient(cast(Any, app), raise_server_exceptions=False) as c:
        r = c.get("/p/", headers={"authorization": "Bearer x"})
        results["c"] = (r.status_code, r.json().get("detail"))
        print("(c) registry ctor raising KeyError:", results["c"])
except Exception as exc:
    print("(c) create_app raised", type(exc).__name__, exc)

# Also: the compiler knows the policy at compile time; check that no validation references the registry token
import inspect
import bustan.platform.http.compiler as comp
src = inspect.getsource(comp)
print("compiler.py mentions AUTHENTICATOR_REGISTRY:", "AUTHENTICATOR_REGISTRY" in src)

a_ok = results.get("a", (None,))[0] == 403 and "Unknown authenticator registry" in str(results.get("a", ("", ""))[1])
b_ok = results.get("b", (None,))[0] == 403
c_ok = results.get("c", (None,))[0] == 500
ctrl_ok = results["control"][0] == 200
print("RESULT:", "CONFIRMED - (a) 403 per request for invisible registry, (b) 403 for async request factory, (c) 500 for ctor error; control 200; no compile-time validation" if (a_ok and b_ok and c_ok and ctrl_ok) else f"REFUTED/PARTIAL - {results}")
