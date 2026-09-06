# ruff: noqa
# Evidence script for finding RI-06 (workflow id F-05) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-05: scope guard bypass via use_factory inject lists and use_existing aliases.

Variant A: SINGLETON factory provider whose inject list names a REQUEST-scoped class.
Variant B: use_existing alias (TRANSIENT) pointing at a REQUEST-scoped class, injected
           into a SINGLETON class.
For each variant:
  1. Without lifespan (TestClient without with-block): does request 2 (bob) see alice?
  2. With lifespan (with TestClient(app)): does startup fail, and with what message?
  3. Control: a SINGLETON class depending DIRECTLY on the request-scoped class must be
     rejected by the guard (shows the guard works for the direct case only).
"""

from __future__ import annotations

from typing import Annotated

from starlette.requests import Request
from starlette.testclient import TestClient

from bustan import Controller, Get, Inject, Injectable, InjectionToken, Module, create_app
from bustan.kernel.errors import ProviderResolutionError

SESSION = InjectionToken("SESSION")
ALIAS = InjectionToken("ALIAS")


def build_factory_variant():
    @Injectable(scope="request")
    class RequestIdentity:
        def __init__(self, request: Request) -> None:
            self.user = request.headers.get("x-user", "anonymous")

    def make_session(identity: RequestIdentity) -> dict[str, str]:
        return {"user": identity.user}

    @Controller("/who")
    class WhoController:
        def __init__(self, session: Annotated[dict, Inject(SESSION)]) -> None:
            self.session = session

        @Get("/")
        def who(self) -> dict:
            return self.session

    @Module(
        controllers=[WhoController],
        providers=[
            RequestIdentity,
            {"provide": SESSION, "use_factory": make_session, "inject": [RequestIdentity]},
        ],
    )
    class AppModule:
        pass

    return AppModule


def build_alias_variant():
    @Injectable(scope="request")
    class RequestIdentity:
        def __init__(self, request: Request) -> None:
            self.user = request.headers.get("x-user", "anonymous")

    @Injectable()
    class SingletonService:
        def __init__(self, identity: Annotated[object, Inject(ALIAS)]) -> None:
            self.identity = identity

        def who(self) -> dict:
            return {"user": self.identity.user}

    @Controller("/who")
    class WhoController:
        def __init__(self, service: SingletonService) -> None:
            self.service = service

        @Get("/")
        def who(self) -> dict:
            return self.service.who()

    @Module(
        controllers=[WhoController],
        providers=[
            RequestIdentity,
            {"provide": ALIAS, "use_existing": RequestIdentity},
            SingletonService,
        ],
    )
    class AppModule:
        pass

    return AppModule


def build_direct_control():
    @Injectable(scope="request")
    class RequestIdentity:
        def __init__(self, request: Request) -> None:
            self.user = request.headers.get("x-user", "anonymous")

    @Injectable()
    class SingletonService:
        def __init__(self, identity: RequestIdentity) -> None:
            self.identity = identity

    @Controller("/who")
    class WhoController:
        def __init__(self, service: SingletonService) -> None:
            self.service = service

        @Get("/")
        def who(self) -> dict:
            return {"user": self.service.identity.user}

    @Module(controllers=[WhoController], providers=[RequestIdentity, SingletonService])
    class AppModule:
        pass

    return AppModule


def run_without_lifespan(name: str, module_factory) -> bool:
    app = create_app(module_factory())
    client = TestClient(app)  # no with-block: lifespan/startup never runs
    r1 = client.get("/who/", headers={"x-user": "alice"})
    r2 = client.get("/who/", headers={"x-user": "bob"})
    print(f"[{name}] no-lifespan: alice -> {r1.status_code} {r1.text}")
    print(f"[{name}] no-lifespan: bob   -> {r2.status_code} {r2.text}")
    leaked = r2.status_code == 200 and r2.json().get("user") == "alice"
    if leaked:
        print(f"[{name}] FAIL: bob received alice's request-scoped identity (leak across requests)")
    else:
        print(f"[{name}] PASS: no leak observed")
    return leaked


def run_with_lifespan(name: str, module_factory) -> str:
    app = create_app(module_factory())
    try:
        with TestClient(app) as client:
            r1 = client.get("/who/", headers={"x-user": "alice"})
            r2 = client.get("/who/", headers={"x-user": "bob"})
            print(f"[{name}] lifespan: alice -> {r1.status_code} {r1.text}")
            print(f"[{name}] lifespan: bob   -> {r2.status_code} {r2.text}")
            return "started"
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        # walk the cause chain for the innermost ProviderResolutionError
        cause = exc
        while cause is not None:
            if isinstance(cause, ProviderResolutionError):
                msg = str(cause)
            cause = cause.__cause__
        print(f"[{name}] lifespan: startup raised {type(exc).__name__}: {msg[:300]}")
        return msg


def main() -> None:
    overall_confirmed = True

    for name, factory in (("factory", build_factory_variant), ("alias", build_alias_variant)):
        leaked = run_without_lifespan(name, factory)
        msg = run_with_lifespan(name, factory)
        guard_msg = "can only be injected into request-scoped providers or controllers" in msg
        active_req_msg = "requires an active request" in msg
        print(
            f"[{name}] lifespan startup error mentions guard rule: {guard_msg}; "
            f"mentions 'requires an active request': {active_req_msg}"
        )
        overall_confirmed = overall_confirmed and leaked and active_req_msg and not guard_msg

    # Control: direct constructor dependency IS guarded
    app = create_app(build_direct_control())
    client = TestClient(app)
    r = client.get("/who/", headers={"x-user": "alice"})
    print(f"[direct-control] no-lifespan: alice -> {r.status_code} {r.text[:200]}")
    direct_blocked = r.status_code == 500
    print(
        f"[direct-control] {'PASS' if direct_blocked else 'FAIL'}: direct singleton->request dependency "
        f"{'is rejected (500)' if direct_blocked else 'was NOT rejected'}"
    )

    if overall_confirmed and direct_blocked:
        print("RESULT: CONFIRMED - factory inject and use_existing alias bypass the scope guard; "
              "leak without lifespan; misleading 'requires an active request' with lifespan")
    else:
        print("RESULT: NOT CONFIRMED as described")


if __name__ == "__main__":
    main()
