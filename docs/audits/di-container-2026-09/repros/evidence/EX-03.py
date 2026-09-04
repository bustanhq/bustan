# ruff: noqa
# Evidence script for finding EX-03 (workflow id F-83) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-83: middleware exception path is unguarded for DI failures.

Claim: when a route middleware raises and the controller cannot be built
(ProviderResolutionError), execute_http_exception has no except block, so the
DI error escapes to Starlette's ServerErrorMiddleware: text/plain 500 with
debug=False, full traceback with debug=True, and finish_request never runs.
"""
import logging
from typing import Any, cast

import anyio
from starlette.testclient import TestClient

from bustan import Controller, Get, Injectable, Module, Scope, create_app
from bustan.logger.observability import ObservabilityHooks
from bustan.pipeline.middleware import Middleware, MiddlewareConsumer

logging.basicConfig(level=logging.CRITICAL)


@Injectable()
class Svc:
    def __init__(self, missing: "DoesNotExist") -> None: ...  # noqa: F821


class Boom(Middleware):
    async def use(self, request, call_next):
        raise RuntimeError("middleware failure")


@Controller("/y", scope=Scope.TRANSIENT)
class Y:
    def __init__(self, svc: Svc) -> None: ...

    @Get("/bad")
    def bad(self) -> dict:
        return {}


@Controller("/ok")
class Ok:
    @Get("/")
    def ok(self) -> dict:
        return {"ok": True}


@Controller("/z", scope=Scope.TRANSIENT)
class Z:
    def __init__(self, svc: Svc) -> None: ...

    @Get("/mw")
    def mw(self) -> dict:
        return {}


@Module(controllers=[Ok, Y, Z], providers=[])
class M:
    def configure(self, consumer: MiddlewareConsumer) -> None:
        consumer.apply(Boom).for_routes(Z)


class CountingMetrics:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def record_request(self, *, labels: dict[str, str]) -> None:
        self.calls.append(labels)


results: dict[str, bool] = {}

# --- 1. response contract with debug=False / debug=True via TestClient ---
for debug in (False, True):
    app = create_app(M, debug=debug)
    with TestClient(cast(Any, app), raise_server_exceptions=False) as client:
        normal = client.get("/y/bad")
        mw = client.get("/z/mw")
        print(f"[debug={debug}] normal path : {normal.status_code} {normal.headers.get('content-type')} {normal.text[:80]!r}")
        print(f"[debug={debug}] middleware  : {mw.status_code} {mw.headers.get('content-type')} {mw.text[:80]!r}")
        if not debug:
            results["normal_is_json_500"] = (
                normal.status_code == 500
                and "application/json" in (normal.headers.get("content-type") or "")
            )
            results["mw_is_text_plain_500"] = (
                mw.status_code == 500
                and "text/plain" in (mw.headers.get("content-type") or "")
                and mw.text == "Internal Server Error"
            )
        else:
            leaked = ("ProviderResolutionError" in mw.text) or ("resolver.py" in mw.text)
            print(f"[debug=True] middleware body length={len(mw.text)}; contains ProviderResolutionError={'ProviderResolutionError' in mw.text}; contains resolver.py={'resolver.py' in mw.text}")
            results["debug_traceback_leaks_di_internals"] = leaked
            results["debug_normal_path_does_not_leak"] = "ProviderResolutionError" not in normal.text


# --- 2. observability finish_request never called on middleware path ---
async def run_asgi(app, path: str) -> int:
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [(b"host", b"testserver")],
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
    }
    status = {"code": 0}

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        if message["type"] == "http.response.start":
            status["code"] = message["status"]

    # Starlette's ServerErrorMiddleware sends the 500 and then re-raises the
    # exception to the server; a direct in-process ASGI call sees that re-raise.
    try:
        await app(scope, receive, send)
    except Exception as exc:  # noqa: BLE001
        print(f"    (exception escaped the ASGI app: {type(exc).__name__})")
    return status["code"]


async def lifespan(app, event: str) -> None:
    done = anyio.Event()

    async def receive():
        return {"type": f"lifespan.{event}"}

    async def send(message):
        if message["type"].startswith(f"lifespan.{event}.complete"):
            done.set()

    async with anyio.create_task_group() as tg:
        tg.start_soon(app, {"type": "lifespan", "asgi": {"version": "3.0"}}, receive, send)
        await done.wait()
        tg.cancel_scope.cancel()


async def metrics_check() -> None:
    app = create_app(M, debug=False)
    metrics = CountingMetrics()
    with ObservabilityHooks.scoped_override(ObservabilityHooks(metrics=metrics)):
        await lifespan(app, "startup")
        code_ok = await run_asgi(app, "/ok")
        print(f"metrics: healthy route status={code_ok} finish_request calls={len(metrics.calls)} (harness sanity)")
        results["harness_records_healthy_request"] = len(metrics.calls) == 1
        before = len(metrics.calls)
        code_normal = await run_asgi(app, "/y/bad")
        after_normal = len(metrics.calls)
        code_mw = await run_asgi(app, "/z/mw")
        after_mw = len(metrics.calls)
    print(f"metrics: normal path status={code_normal} finish_request calls={after_normal - before}")
    print(f"metrics: middleware path status={code_mw} finish_request calls={after_mw - after_normal}")
    # The finding implies observability is skipped ONLY on the middleware path.
    # execution.py:145 calls start_request after factory.instantiate (:122), so
    # a controller DI failure leaves observation=None on the normal path as well.
    results["normal_path_ALSO_skips_metric_for_DI_failure"] = (after_normal - before) == 0
    results["mw_path_skips_metric"] = (after_mw - after_normal) == 0


anyio.run(metrics_check)

print()
for key, value in results.items():
    print(f"  {'ok ' if value else 'NO '} {key}")
confirmed = all(results.values())
print("RESULT:", "CONFIRMED (500 contract + debug traceback leak); observability sub-claim is NOT path-specific: both paths skip finish_request for a controller DI failure" if confirmed else "PARTIAL - see flags above")
