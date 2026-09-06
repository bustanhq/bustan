# ruff: noqa
# Evidence script for finding CR-04 (workflow id F-22) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-22: request-scoped cache writes are unlocked (resolver.py:151-152, 268-269, 883-888;
controller_factory.py:55-63). Concurrent resolution inside ONE request builds two instances,
contradicting docs/REQUEST_SCOPED_PROVIDERS.md 'One cached instance per request'.

Case 1: two threads share one Request and call container.resolve(Identity, request=req).
Case 2: two anyio tasks share one Request and call resolve_async(AsyncIdentity), whose async
        factory dependency yields at an await.
Case 3: two threads share one Request and call ControllerFactory.instantiate for a
        request-scoped controller.
Case 4 (control): SINGLETON under the same thread race builds exactly one instance.
"""
from __future__ import annotations

import threading
import time
from typing import Annotated, Any, cast

import anyio
from starlette.requests import Request

from bustan import Controller, Get, Inject, Injectable, Module, Scope
from bustan.kernel.ioc.container import build_container
from bustan.kernel.module.graph import build_module_graph
from bustan.runtime.controller_factory import ControllerFactory


def build_request() -> Request:
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET",
        "scheme": "http", "path": "/", "raw_path": b"/", "query_string": b"",
        "headers": [(b"host", b"t")], "client": ("c", 1), "server": ("s", 80), "path_params": {},
    }

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(scope, receive)


built_identity: list[object] = []


@Injectable(scope=Scope.REQUEST)
class Identity:
    def __init__(self, request: Request) -> None:
        built_identity.append(self)
        time.sleep(0.2)


async def slow_conn() -> str:
    await anyio.sleep(0.2)
    return "conn"


built_async: list[object] = []


@Injectable(scope=Scope.REQUEST)
class AsyncIdentity:
    def __init__(self, request: Request, conn: Annotated[object, Inject("conn")]) -> None:
        built_async.append(self)


built_singleton: list[object] = []


@Injectable()
class SlowSingleton:
    def __init__(self) -> None:
        built_singleton.append(self)
        time.sleep(0.2)


built_controller: list[object] = []


@Controller("/c", scope=Scope.REQUEST)
class ReqController:
    def __init__(self, request: Request) -> None:
        built_controller.append(self)
        time.sleep(0.2)

    @Get("/")
    def get(self) -> dict[str, str]:
        return {}


@Module(
    controllers=[ReqController],
    providers=[
        Identity,
        AsyncIdentity,
        SlowSingleton,
        {"provide": "conn", "use_factory": slow_conn, "scope": "transient"},
    ],
)
class AppModule:
    pass


container = build_container(build_module_graph(AppModule))
module_key = container.module_graph.root_key


def race_threads(fn: Any) -> list[object]:
    out: list[object] = []
    threads = [threading.Thread(target=lambda: out.append(fn())) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return out


# Case 1
req1 = build_request()
out1 = race_threads(lambda: container.resolve(Identity, module=module_key, request=req1))
c1_built, c1_distinct = len(built_identity), len({id(o) for o in out1})
print(f"case1 sync threads, one request: Identity built={c1_built} distinct returned={c1_distinct}")

# Case 2
out2: list[object] = []


async def case2() -> None:
    req2 = build_request()

    async def go() -> None:
        out2.append(await container.resolve_async(AsyncIdentity, module=module_key, request=req2))

    async with anyio.create_task_group() as tg:
        tg.start_soon(go)
        tg.start_soon(go)


anyio.run(case2)
c2_built, c2_distinct = len(built_async), len({id(o) for o in out2})
print(f"case2 async tasks, one request: AsyncIdentity built={c2_built} distinct returned={c2_distinct}")

# Case 3
factory = ControllerFactory(container)
req3 = build_request()
out3 = race_threads(lambda: factory.instantiate(ReqController, module=module_key, request=req3))
c3_built, c3_distinct = len(built_controller), len({id(o) for o in out3})
print(f"case3 sync threads, one request: request-scoped controller built={c3_built} distinct returned={c3_distinct}")

# Case 4 (control)
out4 = race_threads(lambda: container.resolve(SlowSingleton, module=module_key))
c4_built, c4_distinct = len(built_singleton), len({id(o) for o in out4})
print(f"case4 control, singleton under same race: built={c4_built} distinct returned={c4_distinct}")

confirmed = (c1_distinct > 1 or c2_distinct > 1 or c3_distinct > 1) and c4_distinct == 1
print(
    "F-22", "CONFIRMED" if confirmed else "REFUTED",
    "- request scope handed out >1 instance within one request while singleton stayed unique:",
    confirmed,
)
