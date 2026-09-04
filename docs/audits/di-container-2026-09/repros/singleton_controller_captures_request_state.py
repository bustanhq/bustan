"""RI-01: a default-scope (singleton) controller that injects a request-scoped provider or the
Request itself is built once and then serves the first caller's state to every later caller.

docs/REQUEST_SCOPED_PROVIDERS.md promises a ProviderResolutionError for this shape; no error is raised.
"""

from starlette.requests import Request
from starlette.testclient import TestClient

from bustan import Controller, Get, Injectable, Module, create_app


@Injectable(scope="request")
class RequestIdentity:
    def __init__(self, request: Request) -> None:
        self.user_id = request.headers.get("x-user-id", "anonymous")


@Controller("/me")
class MeController:
    def __init__(self, identity: RequestIdentity) -> None:
        self.identity = identity

    @Get("/")
    def me(self) -> dict[str, str]:
        return {"user": self.identity.user_id}


@Controller("/raw")
class RawController:
    def __init__(self, request: Request) -> None:
        self.request = request

    @Get("/")
    def raw(self) -> dict[str, str]:
        return {"user": self.request.headers.get("x-user-id", "anonymous")}


@Module(controllers=[MeController, RawController], providers=[RequestIdentity])
class AppModule:
    pass


def main() -> None:
    app = create_app(AppModule)
    with TestClient(app) as client:
        for path, label in (("/me/", "RI-01a"), ("/raw/", "RI-01b")):
            first = client.get(path, headers={"x-user-id": "alice"}).json()["user"]
            second = client.get(path, headers={"x-user-id": "bob"}).json()["user"]
            if second == "alice":
                print(
                    f"RESULT: {label} REPRODUCED - {path} answered {first!r} then {second!r}; bob saw alice"
                )
            else:
                print(f"RESULT: {label} FIXED - {path} answered {first!r} then {second!r}")


if __name__ == "__main__":
    main()
