# ruff: noqa
# Evidence script for finding OL-09 (workflow id F-42) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-42: async use_factory providers only work for singleton scope over HTTP."""
from typing import Annotated

from starlette.testclient import TestClient

from bustan import Controller, Get, Inject, Module, Scope, create_app
from bustan.kernel.ioc.container import Container
from bustan.kernel.ioc.tokens import REQUEST

TOKEN = object()


async def load_session(request) -> dict[str, str]:
    return {"kind": "per-request", "path": request.url.path}


@Controller("/", scope=Scope.REQUEST)
class Ctl:
    def __init__(self, ctx: Annotated[object, Inject(TOKEN)]) -> None:
        self.ctx = ctx

    @Get("/")
    def index(self) -> object:
        return self.ctx


statuses: dict[str, tuple[int, str]] = {}
for scope in ("request", "transient", "singleton"):
    inject = (REQUEST,) if scope != "singleton" else ()

    async def factory(*args, _scope=scope):
        return {"kind": _scope}

    @Module(
        providers=[{"provide": TOKEN, "use_factory": factory, "inject": inject, "scope": scope}],
        controllers=[Ctl],
    )
    class AppModule:
        pass

    app = create_app(AppModule)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/")
    statuses[scope] = (response.status_code, response.text[:200])
    print(f"scope={scope:9s} status={response.status_code} body={response.text[:160]!r}")

# Show the underlying exception for request scope
async def factory_req(request):
    return {"kind": "request"}

@Module(providers=[{"provide": TOKEN, "use_factory": factory_req, "inject": (REQUEST,), "scope": "request"}], controllers=[Ctl])
class AppModule2:
    pass

app = create_app(AppModule2)
try:
    with TestClient(app, raise_server_exceptions=True) as client:
        client.get("/")
    print("no exception raised for request scope")
except Exception as exc:  # noqa: BLE001
    print("request-scope underlying exception:", type(exc).__name__, str(exc)[:200])

print("Container has instantiate_class_async:", hasattr(Container, "instantiate_class_async"))
print("Container has call_factory_async:", hasattr(Container, "call_factory_async"))

confirmed = statuses["request"][0] == 500 and statuses["transient"][0] == 500 and statuses["singleton"][0] == 200
print("OVERALL:", "CONFIRMED" if confirmed else "REFUTED", statuses)
