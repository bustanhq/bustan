"""RI-06: the request-scope guard only inspects class constructor parameters. A singleton
use_factory provider with inject=[RequestScoped] and a use_existing alias (forced TRANSIENT)
pointing at a request-scoped binding both slip through. With the lifespan running, eager
singleton construction fails at startup with a misleading 'requires an active request' error;
without the lifespan (TestClient not used as a context manager, or any host that skips
lifespan) the first request's state is captured for the process lifetime.
"""

from typing import Annotated

from starlette.requests import Request
from starlette.testclient import TestClient

from bustan import Controller, Get, Inject, Injectable, InjectionToken, Module, Scope, create_app
from bustan.errors import ProviderResolutionError


@Injectable(scope="request")
class RequestIdentity:
    def __init__(self, request: Request) -> None:
        self.user_id = request.headers.get("x-user-id", "anonymous")


SNAPSHOT = InjectionToken("SNAPSHOT")
ALIAS = InjectionToken("ALIAS")


def make_snapshot(identity: RequestIdentity) -> dict[str, str]:
    return {"user": identity.user_id}


@Injectable()
class SingletonViaAlias:
    def __init__(self, identity: Annotated[object, Inject(ALIAS)]) -> None:
        self.identity = identity


@Controller("/snap", scope=Scope.REQUEST)
class SnapController:
    def __init__(
        self, snap: Annotated[dict, Inject(SNAPSHOT)], via_alias: SingletonViaAlias
    ) -> None:
        self.snap = snap
        self.via_alias = via_alias

    @Get("/")
    def get(self) -> dict[str, str]:
        identity = self.via_alias.identity
        assert isinstance(identity, RequestIdentity)
        return {"factory": self.snap["user"], "alias": identity.user_id}


@Module(
    controllers=[SnapController],
    providers=[
        RequestIdentity,
        {"provide": SNAPSHOT, "use_factory": make_snapshot, "inject": [RequestIdentity]},
        {"provide": ALIAS, "use_existing": RequestIdentity},
        SingletonViaAlias,
    ],
)
class AppModule:
    pass


def main() -> None:
    try:
        with TestClient(create_app(AppModule)) as client:
            client.get("/snap/", headers={"x-user-id": "alice"})
        print(
            "RESULT: RI-06a REPRODUCED - startup accepted a singleton that depends on request scope"
        )
    except ProviderResolutionError as exc:
        message = str(exc)
        if "request-scoped provider" in message and "can only be injected" in message:
            print(
                "RESULT: RI-06a FIXED - startup rejected the shape with the documented guard error"
            )
        else:
            print(
                "RESULT: RI-06a REPRODUCED - startup failed with a misleading error: "
                f"{message[:90]}"
            )

    client = TestClient(create_app(AppModule))  # no lifespan: singletons are built lazily
    first = client.get("/snap/", headers={"x-user-id": "alice"}).json()
    second = client.get("/snap/", headers={"x-user-id": "bob"}).json()
    for key, label in (("factory", "RI-06b"), ("alias", "RI-06c")):
        if second[key] == "alice":
            print(
                f"RESULT: {label} REPRODUCED - {key} path served alice to bob: {first} then "
                f"{second}"
            )
        else:
            print(f"RESULT: {label} FIXED - {key} path isolated: {first} then {second}")


if __name__ == "__main__":
    main()
