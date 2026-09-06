# ruff: noqa
# Evidence script for finding QA-01 (workflow id F-46) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
# Left naming the pre-rename package tree, on purpose. The packages were renamed after
# this ran - core to kernel, platform/http to runtime, logger to observability, config
# to configuration - but the file this script reads by path, src/bustan/core/ioc/resolver.py,
# was deleted rather than renamed and has no successor at any path. Renaming the names
# around it would not let it run, and would claim it had measured a tree it never saw.
"""F-46: layering (core -> platform.http / starlette) and HttpRequest not injectable into providers.

Part 1: static import facts (core.module.graph imports platform.http.metadata; core.ioc.resolver imports
starlette; FRAMEWORK_OWNED_TYPES / ResolvedT are unused).
Part 2: runtime: @Injectable(scope='request') provider annotated with the adapter-neutral HttpRequest,
injected into a request-scoped controller -> expect 500 per the finding; the same provider annotated with
starlette Request works.
"""
from __future__ import annotations

import ast
import pathlib
import sys

from starlette.requests import Request
from starlette.testclient import TestClient

from bustan import Controller, Get, HttpRequest, Injectable, Module, Scope, create_app

ROOT = pathlib.Path("/home/user/bustan/src/bustan")

# ---- Part 1: static facts
graph_src = (ROOT / "core/module/graph.py").read_text()
resolver_src = (ROOT / "core/ioc/resolver.py").read_text()
scopes_src = (ROOT / "core/ioc/scopes.py").read_text()
container_src = (ROOT / "core/ioc/container.py").read_text()
print("graph.py imports platform.http.metadata:", "from ...platform.http.metadata import" in graph_src)
print("resolver.py imports starlette Starlette/Request/Response:",
      all(s in resolver_src for s in ("from starlette.applications import Starlette",
                                      "from starlette.requests import Request",
                                      "from starlette.responses import Response")))
print("scopes.py imports starlette Request:", "from starlette.requests import Request" in scopes_src)
print("container.py imports starlette Request:", "from starlette.requests import Request" in container_src)

# usages of FRAMEWORK_OWNED_TYPES / ResolvedT anywhere in src or tests
uses = {"FRAMEWORK_OWNED_TYPES": 0, "ResolvedT": 0}
for p in list(ROOT.rglob("*.py")) + list(pathlib.Path("/home/user/bustan/tests").rglob("*.py")):
    src = p.read_text()
    try:
        parsed = ast.parse(src)
    except SyntaxError:
        continue  # CLI scaffolding templates are not valid Python
    for name in uses:
        for node in ast.walk(parsed):
            if isinstance(node, ast.Name) and node.id == name and isinstance(node.ctx, ast.Load):
                uses[name] += 1
print("Load-references to FRAMEWORK_OWNED_TYPES / ResolvedT (0 = defined but never used):", uses)

# does importing the module graph pull in the http platform? (fresh interpreter; note that importing any
# bustan submodule also executes bustan/__init__.py, which imports the platform anyway)
import subprocess
probe = subprocess.run(
    [sys.executable, "-c",
     "import importlib.util, sys; import bustan.core.module.graph as g; "
     "print(g.get_controller_metadata.__module__, 'bustan.platform.http.metadata' in sys.modules)"],
    capture_output=True, text=True, cwd="/home/user/bustan")
print("graph.get_controller_metadata comes from / platform loaded:", probe.stdout.strip(), probe.stderr.strip()[-200:])


# ---- Part 2: runtime
@Injectable(scope="request")
class NeutralCtx:
    def __init__(self, request: HttpRequest) -> None:
        self.request = request


@Controller("/neutral", scope=Scope.REQUEST)
class NeutralCtl:
    def __init__(self, ctx: NeutralCtx) -> None:
        self.ctx = ctx

    @Get("/")
    def index(self) -> dict[str, str]:
        return {"path": self.ctx.request.path}


@Injectable(scope="request")
class NativeCtx:
    def __init__(self, request: Request) -> None:
        self.request = request


@Controller("/native", scope=Scope.REQUEST)
class NativeCtl:
    def __init__(self, ctx: NativeCtx) -> None:
        self.ctx = ctx

    @Get("/")
    def index(self) -> dict[str, str]:
        return {"path": self.ctx.request.url.path}


@Module(providers=[NeutralCtx, NativeCtx], controllers=[NeutralCtl, NativeCtl])
class AppModule:
    pass


with TestClient(create_app(AppModule), raise_server_exceptions=False) as client:
    neutral = client.get("/neutral/")
    native = client.get("/native/")
print("provider annotated with starlette Request:", native.status_code, native.text[:80])
print("provider annotated with HttpRequest:      ", neutral.status_code, neutral.text[:160])

# also try direct container resolution to surface the exact error text
app = create_app(AppModule)
from bustan.core.errors import ProviderResolutionError
try:
    app.container.instantiate_class(NeutralCtx, module=AppModule)
except ProviderResolutionError as exc:
    print("direct instantiate_class(NeutralCtx) ->", str(exc)[:200])

if native.status_code == 200 and neutral.status_code == 500:
    print("PASS: HttpRequest is not injectable into providers while starlette Request is (500 vs 200)")
else:
    print("FAIL: unexpected status codes")
