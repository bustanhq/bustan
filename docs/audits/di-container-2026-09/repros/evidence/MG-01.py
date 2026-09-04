# ruff: noqa
# Evidence script for finding MG-01 (workflow id F-08) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-08: re-exporting an imported token passes graph validation but fails at resolution.

Variant A: MidModule imports BottomModule (exports DeepService) and re-exports DeepService;
           AppModule imports MidModule; controller depends on DeepService.
Variant B: @Global facade module imports BottomModule and re-exports DeepService;
           AppModule imports the facade; controller depends on DeepService.
Checks: build_module_graph, create_app, lifespan startup, ApplicationContext.get,
container.resolve from the root module, and the HTTP route.
"""

from __future__ import annotations

from starlette.testclient import TestClient

from bustan import Controller, Get, Global, Injectable, Module, create_app
from bustan.core.errors import ProviderResolutionError
from bustan.core.module.graph import build_module_graph


def build_two_hop():
    @Injectable()
    class DeepService:
        def ping(self) -> str:
            return "deep"

    @Module(providers=[DeepService], exports=[DeepService])
    class BottomModule:
        pass

    @Module(imports=[BottomModule], exports=[DeepService])
    class MidModule:
        pass

    @Controller("/deep")
    class DeepController:
        def __init__(self, svc: DeepService) -> None:
            self.svc = svc

        @Get("/")
        def get(self) -> dict:
            return {"ping": self.svc.ping()}

    @Module(imports=[MidModule], controllers=[DeepController])
    class AppModule:
        pass

    return AppModule, DeepService


def build_global_facade():
    @Injectable()
    class DeepService:
        def ping(self) -> str:
            return "deep"

    @Module(providers=[DeepService], exports=[DeepService])
    class BottomModule:
        pass

    @Global()
    @Module(imports=[BottomModule], exports=[DeepService])
    class FacadeModule:
        pass

    @Controller("/deep")
    class DeepController:
        def __init__(self, svc: DeepService) -> None:
            self.svc = svc

        @Get("/")
        def get(self) -> dict:
            return {"ping": self.svc.ping()}

    @Module(imports=[FacadeModule], controllers=[DeepController])
    class AppModule:
        pass

    return AppModule, DeepService


def exercise(name: str, builder) -> bool:
    AppModule, DeepService = builder()
    graph = build_module_graph(AppModule)
    print(f"[{name}] build_module_graph OK: nodes={[type(n.key).__name__ if not isinstance(n.key, type) else n.key.__name__ for n in graph.nodes]}")

    app = create_app(AppModule)
    root_vis = app.container.registry.module_visibility[app.root_key]
    declaring = root_vis.get(DeepService)
    has_binding = (declaring, DeepService) in app.container.registry.bindings
    print(f"[{name}] visibility[root][DeepService] -> {getattr(declaring, '__name__', declaring)}; binding exists under it: {has_binding}")

    startup_ok = False
    resolve_err = None
    http_status = None
    try:
        with TestClient(app) as client:
            startup_ok = True
            try:
                app.get(DeepService)
                print(f"[{name}] app.get(DeepService) succeeded")
            except ProviderResolutionError as exc:
                resolve_err = str(exc)
                print(f"[{name}] app.get(DeepService) raised: {exc}")
            r = client.get("/deep/")
            http_status = r.status_code
            print(f"[{name}] GET /deep/ -> {r.status_code} {r.text[:120]}")
    except Exception as exc:  # noqa: BLE001
        print(f"[{name}] lifespan startup raised: {type(exc).__name__}: {exc}")

    defect = startup_ok and resolve_err is not None and "Binding not found" in resolve_err and http_status == 500
    print(f"[{name}] {'FAIL (defect present)' if defect else 'PASS (no defect)'}")
    return defect


def main() -> None:
    a = exercise("two-hop", build_two_hop)
    b = exercise("global-facade", build_global_facade)
    if a and b:
        print("RESULT: CONFIRMED - re-export passes validation and startup, fails at resolve/HTTP with 'Binding not found'")
    elif a or b:
        print("RESULT: PARTIALLY CONFIRMED")
    else:
        print("RESULT: NOT CONFIRMED")


if __name__ == "__main__":
    main()
