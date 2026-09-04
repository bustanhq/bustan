# ruff: noqa
# Evidence script for finding RF-05 (workflow id F-36) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-36: APPLICATION token / Starlette-annotated parameter resolve to different object
types depending on the resolution path."""
from __future__ import annotations
from typing import Annotated
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.testclient import TestClient
from bustan import Controller, Get, Injectable, Module, Inject, create_app, create_app_context
from bustan.app.application import Application, ApplicationContext
from bustan.core.ioc.tokens import APPLICATION

@Injectable(scope="transient")
class AppProbe:
    def __init__(self, app: Annotated[object, Inject(APPLICATION)]) -> None:
        self.app = app

@Injectable(scope="transient")
class StarletteProbe:
    def __init__(self, app: Starlette) -> None:
        self.app = app

@Controller("/p")
class ProbeController:
    def __init__(self, probe: AppProbe, sprobe: StarletteProbe) -> None:
        self.probe = probe
        self.sprobe = sprobe
    @Get("/")
    def read(self) -> dict:
        return {"APPLICATION": type(self.probe.app).__name__,
                "Starlette_annotated": type(self.sprobe.app).__name__,
                "Starlette_annotated_isinstance_Starlette": isinstance(self.sprobe.app, Starlette)}

@Module(controllers=[ProbeController], providers=[AppProbe, StarletteProbe])
class M: ...

seen = {}
ctx = create_app_context(M)
a = ctx.get(AppProbe).app
s = ctx.get(StarletteProbe).app
seen["create_app_context.get"] = type(a).__name__
print("create_app_context.get -> APPLICATION:", type(a).__name__, "isinstance ApplicationContext:", isinstance(a, ApplicationContext),
      "| Starlette-annotated:", type(s).__name__, "isinstance Starlette:", isinstance(s, Starlette))

app = create_app(M)
a2 = app.get(AppProbe).app
seen["Application.get"] = type(a2).__name__
print("Application.get -> APPLICATION:", type(a2).__name__, "isinstance Application:", isinstance(a2, Application),
      "isinstance Starlette:", isinstance(a2, Starlette))

with TestClient(app) as client:
    body = client.get("/p/").json()
    seen["http"] = body["APPLICATION"]
    print("HTTP path ->", body)

scope = {"type": "http", "method": "GET", "path": "/", "headers": [], "app": app.get_http_server()}
raw = app.container.resolve(AppProbe, module=M, request=Request(scope)).app
seen["container.resolve(request=)"] = type(raw).__name__
print("container.resolve(request=...) -> APPLICATION:", type(raw).__name__, "isinstance Starlette:", isinstance(raw, Starlette),
      "isinstance Application:", isinstance(raw, Application))

distinct = set(seen.values())
print("RESULT:", f"CONFIRMED - APPLICATION resolves to {len(distinct)} distinct types: {seen}"
      if len(distinct) >= 3 else f"REFUTED - only {distinct}: {seen}")
