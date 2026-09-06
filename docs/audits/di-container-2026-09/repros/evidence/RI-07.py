# ruff: noqa
# Evidence script for finding RI-07 (workflow id F-18) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-18: nested resolve(token, request=None) inherits the outer request ContextVar,
so a singleton can pull request-scoped state imperatively via app.get()."""
from __future__ import annotations

from typing import Any, cast

from starlette.requests import Request
from starlette.testclient import TestClient

from bustan import Controller, Get, Injectable, Module, create_app
from bustan.kernel.errors import ProviderResolutionError

APP_HOLDER: dict[str, Any] = {}


@Injectable(scope="request")
class RequestIdentity:
    def __init__(self, request: Request) -> None:
        self.user_id = request.headers.get("x-user-id", "anonymous")


@Injectable  # SINGLETON
class Cache:
    def __init__(self) -> None:
        app = APP_HOLDER["app"]
        # Imperative resolution: ApplicationContext.get is documented as
        # "non-request-scoped resolution" (application.py:53-59).
        try:
            identity = app.get(RequestIdentity)
            self.owner = identity.user_id
        except ProviderResolutionError as exc:
            self.owner = f"unavailable ({exc})"


@Controller("/cache")
class CacheController:
    def __init__(self, cache: Cache) -> None:
        self.cache = cache

    @Get("/")
    def get(self) -> dict[str, str]:
        return {"owner": self.cache.owner}


@Module(providers=[RequestIdentity, Cache], controllers=[CacheController], exports=[Cache])
class AppModule:
    pass


# Part A: no lifespan -> Cache is constructed lazily inside alice's request.
app = create_app(AppModule)
APP_HOLDER["app"] = app
client = TestClient(cast(Any, app))
a = client.get("/cache/", headers={"x-user-id": "alice"}).json()
b = client.get("/cache/", headers={"x-user-id": "bob"}).json()
print("[A] no lifespan: alice ->", a, "| bob ->", b)
leak = a["owner"] == "alice" and b["owner"] == "alice"

# Part B: with lifespan -> Cache built eagerly at startup, outside any request.
app2 = create_app(AppModule)
APP_HOLDER["app"] = app2
with TestClient(cast(Any, app2)) as client2:
    c = client2.get("/cache/", headers={"x-user-id": "carol"}).json()
print("[B] with lifespan: carol ->", c)
dead_under_lifespan = str(c["owner"]).startswith("unavailable")

# Part C: direct container check -- with a request pushed, resolve(request=None)
# still sees the outer request because push_request(None) is a no-op (scopes.py:101-104).
from bustan.kernel.ioc.container import build_container
from bustan.kernel.module.graph import build_module_graph

container = build_container(build_module_graph(AppModule))
scope = {"type": "http", "method": "GET", "path": "/", "headers": [(b"x-user-id", b"alice")], "query_string": b""}
req = Request(scope)
token = container.scope_manager.push_request(req)
try:
    direct = container.resolve(RequestIdentity, module=AppModule, request=None)
    print("[C] with request pushed, container.resolve(RequestIdentity, request=None) ->", direct.user_id)
    direct_leak = direct.user_id == "alice"
finally:
    container.scope_manager.pop_request(token)

# Part D: is the constructor-parameter guard still enforced for the declared form?
@Injectable
class DeclaredSingleton:
    def __init__(self, identity: RequestIdentity) -> None:
        self.identity = identity


@Module(providers=[RequestIdentity, DeclaredSingleton], exports=[DeclaredSingleton])
class GuardModule:
    pass


container2 = build_container(build_module_graph(GuardModule))
token = container2.scope_manager.push_request(req)
try:
    container2.resolve(DeclaredSingleton, module=GuardModule)
    print("[D] declared singleton->request dependency: NOT rejected")
    guard_ok = False
except ProviderResolutionError as exc:
    print("[D] declared singleton->request dependency rejected by guard:", str(exc)[:90])
    guard_ok = True
finally:
    container2.scope_manager.pop_request(token)

print()
print("singleton cached alice's request state and served it to bob:", leak)
print("same feature silently dead under lifespan:", dead_under_lifespan)
print("resolve(request=None) inherited outer request:", direct_leak)
print("declared-parameter guard still fires (imperative path bypasses it):", guard_ok)
print("F-18", "CONFIRMED" if (leak and direct_leak and guard_ok) else "REFUTED")
