"""MG-04: the container never validates the dependency graph of transient or request-scoped
providers or of controllers at bootstrap. An unresolvable dependency starts fine and becomes a 500
on the first request that touches it.
"""

import logging

from starlette.testclient import TestClient

from bustan import Controller, Get, Injectable, Module, Scope, create_app


class NotRegistered:
    pass


@Injectable(scope=Scope.TRANSIENT)
class Broken:
    def __init__(self, dep: NotRegistered) -> None:
        self.dep = dep


@Controller("/x")
class XController:
    def __init__(self, broken: Broken) -> None:
        self.broken = broken

    @Get("/")
    def get(self) -> dict[str, str]:
        return {}


@Module(controllers=[XController], providers=[Broken])
class AppModule:
    pass


def main() -> None:
    logging.disable(logging.CRITICAL)
    try:
        app = create_app(AppModule)
        with TestClient(app) as client:
            status = client.get("/x/").status_code
    except Exception as exc:  # noqa: BLE001 - any bootstrap-time failure means the gap is closed
        print(f"RESULT: MG-04 FIXED - bootstrap rejected the graph: {type(exc).__name__}")
        return
    if status == 500:
        print(
            "RESULT: MG-04 REPRODUCED - app started; unresolvable controller dependency became "
            "HTTP 500"
        )
    else:
        print(f"RESULT: MG-04 FIXED - request returned {status}")


if __name__ == "__main__":
    main()
