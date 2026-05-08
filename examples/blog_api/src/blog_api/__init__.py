"""Reference-style blog API example package."""

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
    """Show the seeded list endpoint and a write that carries request-local context."""

    application = build_application()
    with TestClient(cast(Any, application)) as client:
        print(client.get("/posts").json())
        print(
            client.post(
                "/posts",
                headers={"x-user-id": "ada"},
                json={
                    "title": "Request-scoped context",
                    "body": "Controllers can mix singleton services with request-local state.",
                    "published": True,
                },
            ).json()
        )