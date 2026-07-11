"""Request-scoped pipeline example package."""

from __future__ import annotations

import asyncio
from typing import Any, cast

from starlette.testclient import TestClient

from bustan import Application, create_app

from .app_module import AppModule


def build_application() -> Application:
    return create_app(AppModule)


async def bootstrap(reload: bool = False) -> None:
    application = build_application()
    await application.listen(port=3000, reload=reload)


def main() -> None:
    asyncio.run(bootstrap())


def dev() -> None:
    asyncio.run(bootstrap(reload=True))


def demo() -> None:
    """Show the rejected and accepted paths for the request-scoped pipeline."""

    application = build_application()
    with TestClient(cast(Any, application)) as client:
        print(client.get("/account/me").status_code)
        print(
            client.get(
                "/account/me",
                headers={
                    "x-user-id": "moses",
                    "x-request-id": "req-42",
                },
            ).json()
        )