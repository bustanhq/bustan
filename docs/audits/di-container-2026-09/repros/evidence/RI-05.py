# ruff: noqa
# Evidence script for finding RI-05 (workflow id F-06) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-06: RESPONSE / Response injection has no owner-scope guard.

Variant A: singleton controller (default scope) injecting Response, WITH lifespan.
Variant B: singleton provider HeaderWriter injecting Response, owned by a singleton
           controller, WITHOUT lifespan (with lifespan the provider is built at startup
           where active_response is None and startup fails).
Variant C: control - a REQUEST-scoped controller injecting Response works per request.
Each handler writes x-seen-by and x-count headers into the injected Response and returns
id(response). Expected (if defect present): only the first request carries the headers,
and id(response) is identical across requests.
"""

from __future__ import annotations

from itertools import count

from starlette.responses import Response
from starlette.testclient import TestClient

from bustan import Controller, Get, Injectable, Module, Scope, create_app


def build_singleton_controller():
    counter = count(1)

    @Controller("/hdr")
    class HeaderController:
        def __init__(self, response: Response) -> None:
            self.response = response

        @Get("/")
        def handler(self) -> dict:
            n = next(counter)
            self.response.headers["x-seen-by"] = f"req-{n}"
            self.response.headers["x-count"] = str(n)
            self.response.status_code = 201
            return {"response_id": id(self.response), "n": n}

    @Module(controllers=[HeaderController])
    class AppModule:
        pass

    return AppModule


def build_singleton_provider():
    counter = count(1)

    @Injectable()
    class HeaderWriter:
        def __init__(self, response: Response) -> None:
            self.response = response

        def write(self) -> int:
            n = next(counter)
            self.response.headers["x-seen-by"] = f"req-{n}"
            self.response.headers["x-count"] = str(n)
            return n

    @Controller("/hdr")
    class HeaderController:
        def __init__(self, writer: HeaderWriter) -> None:
            self.writer = writer

        @Get("/")
        def handler(self) -> dict:
            n = self.writer.write()
            return {"response_id": id(self.writer.response), "n": n}

    @Module(controllers=[HeaderController], providers=[HeaderWriter])
    class AppModule:
        pass

    return AppModule


def build_request_controller_control():
    counter = count(1)

    @Controller("/hdr", scope=Scope.REQUEST)
    class HeaderController:
        def __init__(self, response: Response) -> None:
            self.response = response

        @Get("/")
        def handler(self) -> dict:
            n = next(counter)
            self.response.headers["x-seen-by"] = f"req-{n}"
            self.response.headers["x-count"] = str(n)
            return {"response_id": id(self.response), "n": n}

    @Module(controllers=[HeaderController])
    class AppModule:
        pass

    return AppModule


def exercise(name: str, client: TestClient) -> bool:
    ids = []
    header_present = []
    statuses = []
    for i in range(1, 4):
        r = client.get("/hdr/")
        body = r.json() if r.status_code == 200 or r.status_code == 201 else {}
        ids.append(body.get("response_id"))
        header_present.append(r.headers.get("x-seen-by"))
        statuses.append(r.status_code)
        print(
            f"[{name}] request {i}: status={r.status_code} x-seen-by={r.headers.get('x-seen-by')!r} "
            f"x-count={r.headers.get('x-count')!r} response_id={body.get('response_id')}"
        )
    same_object = len(set(ids)) == 1 and ids[0] is not None
    dropped = header_present[0] is not None and all(h is None for h in header_present[1:])
    print(f"[{name}] same Response object across requests: {same_object}; headers dropped after first: {dropped}; statuses={statuses}")
    return same_object and dropped


def main() -> None:
    # A: singleton controller with lifespan
    app = create_app(build_singleton_controller())
    with TestClient(app) as client:
        a = exercise("singleton-controller/lifespan", client)
    print(f"[singleton-controller/lifespan] {'FAIL (defect present)' if a else 'PASS (no defect)'}")

    # B: singleton provider, no lifespan
    app = create_app(build_singleton_provider())
    client = TestClient(app)
    b = exercise("singleton-provider/no-lifespan", client)
    print(f"[singleton-provider/no-lifespan] {'FAIL (defect present)' if b else 'PASS (no defect)'}")

    # B2: singleton provider with lifespan -> expect startup error
    app = create_app(build_singleton_provider())
    try:
        with TestClient(app):
            print("[singleton-provider/lifespan] startup succeeded (unexpected)")
    except Exception as exc:  # noqa: BLE001
        cause = exc
        msg = str(exc)
        while cause is not None:
            msg = str(cause)
            cause = cause.__cause__
        print(f"[singleton-provider/lifespan] startup raised: {msg[:200]}")

    # C: request-scoped controller control
    app = create_app(build_request_controller_control())
    with TestClient(app) as client:
        c = exercise("request-controller/control", client)
    print(f"[request-controller/control] {'FAIL' if c else 'PASS (per-request Response works)'}")

    if a and b and not c:
        print("RESULT: CONFIRMED - singleton owners capture request 1's Response; later header/status writes are dropped")
    else:
        print("RESULT: NOT CONFIRMED as described")


if __name__ == "__main__":
    main()
