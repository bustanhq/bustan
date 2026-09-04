# ruff: noqa
# Evidence script for finding OL-11 (workflow id F-23) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-23: no public way to resolve request-scoped providers from handler / guard code.

Checks (all through a real TestClient request unless noted):
  1. inside a sync handler (worker thread) and an async handler (loop thread):
     scope_manager.active_request is None while active_response/active_application are set
     (execution.py:112-114 push app/response for the whole route; the request is pushed only
      inside resolve/instantiate_class, resolver.py:113/154, 337/346)
  2. container.resolve(Identity, module=root) with no request -> ProviderResolutionError
     (resolver.py:856-860)
  3. ModuleRef.get(Identity) -> same error (module_ref.py:46-48 passes no request)
  4. inside a Guard.can_activate: active_request is None and context.container.resolve
     without request fails; with request=native it works (the PolicyGuard route)
  5. the only working route from a handler is the internal container.resolve(..., request=)
  6. ApplicationContext.get docstring points to app.resolve(); ctx.get(R) and ctx.resolve(R)
     raise identically (application.py:124-139); docs/API_REFERENCE.md mirrors it.
"""
from __future__ import annotations

import inspect
import threading
from typing import Annotated, Any, cast

from starlette.requests import Request
from starlette.testclient import TestClient

from bustan import Controller, Get, Inject, Injectable, Module, UseGuards, create_app, create_app_context
from bustan.addons.module_ref import ModuleRef
from bustan.app.application import ApplicationContext
from bustan.core.errors import ProviderResolutionError
from bustan.core.ioc.tokens import APPLICATION
from bustan.pipeline.guards import Guard


@Injectable(scope="request")
class Identity:
    def __init__(self, request: Request) -> None:
        self.rid = request.headers.get("x-request-id")


guard_seen: dict[str, str] = {}


class ProbeGuard(Guard):
    def can_activate(self, context: Any) -> bool:
        sm = context.container.scope_manager
        guard_seen["active_request"] = type(sm.active_request.get()).__name__
        try:
            context.container.resolve(Identity, module=context.module)
            guard_seen["resolve_no_request"] = "ok"
        except ProviderResolutionError as exc:
            guard_seen["resolve_no_request"] = f"ProviderResolutionError: {exc}"
        native = context.request.native_request
        ident = context.container.resolve(Identity, module=context.module, request=native)
        guard_seen["resolve_with_request"] = f"ok rid={ident.rid}"
        return True


def probe(container: Any, ref: ModuleRef, module: Any, native: Request) -> dict[str, str]:
    sm = container.scope_manager
    out = {
        "thread": threading.current_thread().name,
        "active_request": type(sm.active_request.get()).__name__,
        "active_response": type(sm.active_response.get()).__name__,
        "active_application": type(sm.active_application.get()).__name__,
    }
    try:
        container.resolve(Identity, module=module)
        out["container_resolve_no_request"] = "ok"
    except ProviderResolutionError as exc:
        out["container_resolve_no_request"] = f"ProviderResolutionError: {exc}"
    try:
        ref.get(Identity)
        out["moduleref_get"] = "ok"
    except ProviderResolutionError as exc:
        out["moduleref_get"] = f"ProviderResolutionError: {exc}"
    ident = container.resolve(Identity, module=module, request=native)
    out["container_resolve_with_request"] = f"ok rid={ident.rid}"
    return out


@Controller("/probe")
@UseGuards(ProbeGuard)
class ProbeController:
    def __init__(self, app: Annotated[object, Inject(APPLICATION)], ref: ModuleRef) -> None:
        self.app = cast(Any, app)
        self.ref = ref

    @Get("/sync")
    def sync_probe(self, request: Request) -> dict[str, str]:
        return probe(self.app.container, self.ref, self.app.root_key, request)

    @Get("/async")
    async def async_probe(self, request: Request) -> dict[str, str]:
        return probe(self.app.container, self.ref, self.app.root_key, request)


@Module(controllers=[ProbeController], providers=[Identity, ModuleRef])
class AppModule:
    pass


checks: dict[str, bool] = {}
app = create_app(AppModule)
with TestClient(cast(Any, app)) as client:
    for path in ("/probe/sync", "/probe/async"):
        r = client.get(path, headers={"x-request-id": "abc"})
        print(path, r.status_code)
        body = r.json()
        for k, v in body.items():
            print("   ", k, "=", v)
        tag = path.rsplit("/", 1)[1]
        checks[f"{tag}: active_request unset"] = body["active_request"] == "NoneType"
        checks[f"{tag}: response/app set"] = body["active_response"] != "NoneType" and body["active_application"] != "NoneType"
        checks[f"{tag}: resolve w/o request fails"] = "requires an active request" in body["container_resolve_no_request"]
        checks[f"{tag}: ModuleRef.get fails"] = "requires an active request" in body["moduleref_get"]
        checks[f"{tag}: internal resolve(request=) works"] = body["container_resolve_with_request"] == "ok rid=abc"
    print("guard:")
    for k, v in guard_seen.items():
        print("   ", k, "=", v)
    checks["guard: active_request unset"] = guard_seen["active_request"] == "NoneType"
    checks["guard: resolve w/o request fails"] = "requires an active request" in guard_seen["resolve_no_request"]
    checks["guard: resolve(request=) works"] = guard_seen["resolve_with_request"] == "ok rid=abc"

# 6. docstring / alias
doc = inspect.getdoc(ApplicationContext.get) or ""
print("ApplicationContext.get docstring mentions app.resolve():", "app.resolve()" in doc)
ctx = create_app_context(AppModule)
for name in ("get", "resolve"):
    try:
        getattr(ctx, name)(Identity)
        print(f"ctx.{name}(Identity): ok")
        checks[f"ctx.{name} fails"] = False
    except ProviderResolutionError as exc:
        print(f"ctx.{name}(Identity): ProviderResolutionError: {exc}")
        checks[f"ctx.{name} fails"] = "requires an active request" in str(exc)
checks["docstring points to app.resolve()"] = "app.resolve()" in doc
api_ref = open("/home/user/bustan/docs/API_REFERENCE.md", encoding="utf-8").read()
checks["API_REFERENCE mirrors docstring"] = "decorators (@Param, @Body, etc.) or app.resolve()." in api_ref

# public surface: any public resolve entry point that accepts a request?
public_entry_points = {
    "ApplicationContext.get": inspect.signature(ApplicationContext.get),
    "ApplicationContext.resolve": inspect.signature(ApplicationContext.resolve),
    "ModuleRef.get": inspect.signature(ModuleRef.get),
    "ModuleRef.resolve": inspect.signature(ModuleRef.resolve),
    "ModuleRef.create": inspect.signature(ModuleRef.create),
}
for name, sig in public_entry_points.items():
    print(f"   {name}{sig}")
checks["no public entry point takes request"] = not any("request" in s.parameters for s in public_entry_points.values())

failed = [k for k, v in checks.items() if not v]
for k, v in checks.items():
    print(("PASS " if v else "FAIL ") + k)
print("F-23", "CONFIRMED" if not failed else "REFUTED", "- failed checks:", failed)
