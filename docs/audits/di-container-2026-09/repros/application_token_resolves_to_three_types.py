"""RF-05: the APPLICATION token resolves to a different object type depending on how the
resolution was entered: ApplicationContext from create_app_context().get(), Application from
create_app().get() and from HTTP requests, and the raw Starlette instance when the container is
called with a request but no pushed runtime (request.app fallback). Consumers such as ModuleRef
and DiscoveryService already special-case both shapes, which is the symptom.
"""

from typing import Annotated

from starlette.requests import Request
from starlette.testclient import TestClient

from bustan import (
    APPLICATION,
    Controller,
    Get,
    Inject,
    Injectable,
    Module,
    Scope,
    create_app,
    create_app_context,
)


@Injectable(scope=Scope.TRANSIENT)
class Probe:
    def __init__(self, app: Annotated[object, Inject(APPLICATION)]) -> None:
        self.kind = type(app).__name__


@Controller("/p", scope=Scope.REQUEST)
class ProbeController:
    def __init__(self, probe: Probe) -> None:
        self.probe = probe

    @Get("/")
    def get(self) -> dict[str, str]:
        return {"kind": self.probe.kind}


@Module(controllers=[ProbeController], providers=[Probe])
class AppModule:
    pass


def main() -> None:
    kinds: dict[str, str] = {}
    context = create_app_context(AppModule)
    kinds["create_app_context"] = context.get(Probe).kind
    app = create_app(AppModule)
    kinds["create_app"] = app.get(Probe).kind
    with TestClient(app) as client:
        kinds["http"] = client.get("/p/").json()["kind"]
    scope = {"type": "http", "method": "GET", "path": "/", "headers": [], "app": app.get_http_server()}
    kinds["container.resolve(request=...)"] = app.container.resolve(
        Probe, module=app.root_key, request=Request(scope)
    ).kind
    if len(set(kinds.values())) > 1:
        print(f"RESULT: RF-05 REPRODUCED - APPLICATION resolved to {kinds}")
    else:
        print(f"RESULT: RF-05 FIXED - APPLICATION consistently resolves to {kinds}")


if __name__ == "__main__":
    main()
