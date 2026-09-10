"""Reference-style blog API example package."""

from __future__ import annotations

import asyncio

import uvicorn

from bustan import Application, create_app
from bustan.testing import AsgiTestClient

from .app_module import AppModule


def build_application() -> Application:
    return create_app(AppModule)


async def bootstrap() -> None:
    application = build_application()
    await application.listen(port=3000)


def main() -> None:
    asyncio.run(bootstrap())


def dev() -> None:
    """Serve with uvicorn's reloader watching this project.

    The application is named as an import string rather than built here, because the
    reloader restarts the process that serves it and so has to import the application
    for itself; a live object built in this process would not survive that restart.
    ``factory=True`` names the builder above, so a restarted worker builds exactly what
    every other entry point here builds.
    """

    uvicorn.run("blog_api:build_application", factory=True, port=3000, reload=True)


def demo() -> None:
    """Show the seeded list endpoint and a write that carries request-local context."""

    application = build_application()
    with AsgiTestClient(application) as client:
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
