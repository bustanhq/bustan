# ruff: noqa
# Evidence script for finding PN-09 (workflow id F-87) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
# F-87: factory `inject` tuples naming REQUEST / RESPONSE / APPLICATION /
# INQUIRER go through resolve() -> _get_declaring_module (resolver.py:383-386,
# 409-416, 424-437) and fail with a visibility error; special tokens are only
# understood by the constructor planner (resolver.py:579, 719).
from typing import Annotated

from starlette.requests import Request
from starlette.testclient import TestClient

from bustan import Controller, Get, Inject, Module, Scope, create_app
from bustan.kernel.errors import ProviderResolutionError
from bustan.kernel.ioc.tokens import APPLICATION, INQUIRER, REQUEST, RESPONSE

TOKEN = object()


@Controller("/", scope=Scope.REQUEST)
class Ctl:
    def __init__(self, ctx: Annotated[object, Inject(TOKEN)]) -> None:
        self.ctx = ctx

    @Get("/")
    def index(self) -> object:
        return self.ctx


results = {}
messages = {}
for special_name, special in (
    ("REQUEST", REQUEST), ("RESPONSE", RESPONSE), ("APPLICATION", APPLICATION), ("INQUIRER", INQUIRER)
):

    def factory(dep, _n=special_name):
        return {"got": type(dep).__name__, "token": _n}

    @Module(
        providers=[{"provide": TOKEN, "use_factory": factory, "inject": (special,), "scope": "request"}],
        controllers=[Ctl],
    )
    class AppModule:
        pass

    app = create_app(AppModule)  # container build accepts it silently
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/")
    results[special_name] = response.status_code
    print(f"inject=({special_name},) scope=request -> HTTP {response.status_code} body={response.text[:100]!r}")

    scope = {"type": "http", "method": "GET", "path": "/", "headers": [], "query_string": b"", "state": {}}
    request = Request(scope)
    try:
        app.container.resolve(TOKEN, module=AppModule, request=request)
        messages[special_name] = "resolved (unexpected)"
    except ProviderResolutionError as exc:
        messages[special_name] = str(exc)
    print("  container.resolve ->", messages[special_name][:150])


# Async factory path as well (call_factory_async).
async def afactory(dep):
    return {"got": type(dep).__name__}


@Module(
    providers=[{"provide": TOKEN, "use_factory": afactory, "inject": (REQUEST,), "scope": "request"}],
    controllers=[Ctl],
)
class AsyncModule:
    pass


with TestClient(create_app(AsyncModule), raise_server_exceptions=False) as client:
    ar = client.get("/")
print("async factory inject=(REQUEST,) scope=request -> HTTP", ar.status_code)


# Control: constructor injection of the same token in a request-scoped controller.
@Controller("/", scope=Scope.REQUEST)
class Ctl2:
    def __init__(self, req: Annotated[object, Inject(REQUEST)]) -> None:
        self.req = req

    @Get("/")
    def index(self) -> object:
        return {"got": type(self.req).__name__}


@Module(controllers=[Ctl2])
class ControlModule:
    pass


with TestClient(create_app(ControlModule), raise_server_exceptions=False) as client:
    r = client.get("/")
print("control: Inject(REQUEST) via constructor ->", r.status_code, r.text)

confirmed = (
    all(status == 500 for status in results.values())
    and ar.status_code == 500
    and all("is not available to" in m for m in messages.values())
    and r.status_code == 200
)
print("F-87 RESULT:", "CONFIRMED" if confirmed else "REFUTED", results)
