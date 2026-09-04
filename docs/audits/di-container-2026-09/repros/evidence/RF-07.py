# ruff: noqa
# Evidence script for finding RF-07 (workflow id F-44) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-44: APPLICATION fallback uses hasattr(request, 'app'); Starlette raises KeyError."""
from typing import Annotated

from starlette.applications import Starlette
from starlette.requests import Request

from bustan import APPLICATION, Inject, Injectable, Module
from bustan.core.errors import ProviderResolutionError
from bustan.core.ioc.container import build_container
from bustan.core.module.graph import build_module_graph


@Injectable(scope="transient")
class NeedsApp:
    def __init__(self, app: Annotated[object, Inject(APPLICATION)]) -> None:
        self.app = app


@Module(providers=[NeedsApp])
class AppModule:
    pass


container = build_container(build_module_graph(AppModule))
base_scope = {"type": "http", "method": "GET", "path": "/", "headers": [], "query_string": b""}

# 1. Request without 'app' in ASGI scope
try:
    container.instantiate_class(NeedsApp, module=AppModule, request=Request(dict(base_scope)))
    r1 = "no exception"
except ProviderResolutionError as exc:
    r1 = f"ProviderResolutionError (correct branch): {exc}"
except KeyError as exc:
    r1 = f"KeyError leaked: {exc!r}"
print("no-app request ->", r1)

# 2. Request with app in scope: fallback works
app = Starlette()
inst = container.instantiate_class(NeedsApp, module=AppModule, request=Request({**base_scope, "app": app}))
print("with-app request -> resolved app is Starlette:", inst.app is app)

# 3. No request at all -> ProviderResolutionError
try:
    container.instantiate_class(NeedsApp, module=AppModule)
    r3 = "no exception"
except ProviderResolutionError as exc:
    r3 = f"ProviderResolutionError: {exc}"
print("no request ->", r3)

print("hasattr(Request(no app), 'app') raises:", end=" ")
try:
    hasattr(Request(dict(base_scope)), "app")
    print("no")
except KeyError as exc:
    print("KeyError", exc)

print("OVERALL:", "CONFIRMED" if r1.startswith("KeyError leaked") else "REFUTED")
