"""Request-scoped pipeline example package."""

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

    uvicorn.run(
        "request_scope_pipeline_app:build_application", factory=True, port=3000, reload=True
    )


def demo() -> None:
    """Show the rejected and accepted paths for the request-scoped pipeline."""

    application = build_application()
    with AsgiTestClient(application) as client:
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
