# ruff: noqa
# Evidence script for finding MG-06 (workflow id F-27) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-27: module classes instantiated with no args by middleware compiler (raw TypeError) and again for hooks."""
import traceback
from bustan import Controller, Get, Injectable, Module, create_app, create_app_context
from bustan.core.errors import BustanError
from starlette.testclient import TestClient


@Injectable
class Svc:
    pass


@Module(providers=[Svc])
class NeedsArgsNoHooks:
    def __init__(self, dep: Svc) -> None:
        self.dep = dep


@Module(imports=[NeedsArgsNoHooks])
class App1:
    pass


part1 = None
try:
    create_app_context(App1)
    print("create_app_context(App1): OK")
except Exception as exc:
    print("create_app_context(App1) raised:", type(exc).__name__, exc)

try:
    create_app(App1)
    print("create_app(App1): OK (unexpected)")
except TypeError as exc:
    tb = traceback.extract_tb(exc.__traceback__)
    origin = [f for f in tb if "bustan/" in f.filename][-1]
    print("create_app(App1) raised bare TypeError:", exc)
    print("  is BustanError:", isinstance(exc, BustanError), "; raised from", origin.filename.split("src/")[-1], "line", origin.lineno)
    part1 = ("middleware.py" in origin.filename, not isinstance(exc, BustanError))
except Exception as exc:
    print("create_app(App1) raised:", type(exc).__name__, exc)

print("---- instance count / identity between configure and on_module_init ----")
instances = []
seen = {}


@Module()
class Counting:
    def __init__(self) -> None:
        instances.append(self)

    def configure(self, consumer) -> None:
        seen["configure"] = id(self)

    def on_module_init(self) -> None:
        seen["on_module_init"] = id(self)


app = create_app(Counting)
with TestClient(app):
    pass
print("total module instances created:", len(instances))
print("configure instance id:", seen.get("configure"), "on_module_init instance id:", seen.get("on_module_init"))
part2 = len(instances) == 2 and seen.get("configure") != seen.get("on_module_init")

print("---- controller with lifecycle hook ----")


@Controller("/h")
class HookCtl:
    @Get("/")
    def get(self) -> dict:
        return {}

    def on_module_init(self) -> None:
        pass


@Module(controllers=[HookCtl])
class App3:
    pass


part3 = None
try:
    create_app(App3)
    print("create_app(App3) with controller hook: OK (unexpected)")
    part3 = False
except Exception as exc:
    print("create_app(App3) raised:", type(exc).__name__, exc)
    part3 = type(exc).__name__ == "RouteDefinitionError"

if part1 == (True, True) and part2 and part3:
    print("RESULT: CONFIRMED - bare TypeError from pipeline/middleware.py; two instances with different ids; controller hook rejected")
else:
    print("RESULT: NOT CONFIRMED", part1, part2, part3)
