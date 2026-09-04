"""OL-11: the active request is pushed into the resolver's ContextVar only while the controller is
being instantiated. Inside a handler, ModuleRef.get() of a request-scoped provider fails with
'requires an active request' even though a request is in flight.
"""

from starlette.requests import Request
from starlette.testclient import TestClient

from bustan import Controller, DiscoveryModule, Get, Injectable, Module, ModuleRef, Scope, create_app


@Injectable(scope="request")
class Identity:
    def __init__(self, request: Request) -> None:
        self.user = request.headers.get("x-user-id", "anonymous")


@Controller("/m", scope=Scope.REQUEST)
class LookupController:
    def __init__(self, ref: ModuleRef) -> None:
        self.ref = ref

    @Get("/")
    def get(self) -> dict[str, str]:
        try:
            identity = self.ref.get(Identity)
        except Exception as exc:  # noqa: BLE001 - report whatever the container raised
            return {"error": f"{type(exc).__name__}: {exc}"}
        assert isinstance(identity, Identity)
        return {"user": identity.user}


@Module(imports=[DiscoveryModule], controllers=[LookupController], providers=[Identity])
class AppModule:
    pass


def main() -> None:
    with TestClient(create_app(AppModule)) as client:
        body = client.get("/m/", headers={"x-user-id": "alice"}).json()
    if "error" in body:
        print(f"RESULT: OL-11 REPRODUCED - {body['error'][:110]}")
    else:
        print(f"RESULT: OL-11 FIXED - handler resolved request scope: {body}")


if __name__ == "__main__":
    main()
