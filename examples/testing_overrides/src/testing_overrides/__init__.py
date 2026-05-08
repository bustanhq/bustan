"""Testing override example package."""

from __future__ import annotations

import asyncio
from typing import Any, cast

from starlette.testclient import TestClient

from bustan import Application, create_app
from bustan.testing import create_test_app, override_provider

from .app_module import AppModule
from .fake_greeting_service import FakeGreetingService
from .greeting_service import GreetingService


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
    """Print responses before, during, and after provider overrides."""

    application = create_test_app(
        AppModule,
        provider_overrides={GreetingService: FakeGreetingService("from create_test_app")},
    )

    with TestClient(cast(Any, application)) as client:
        print(client.get("/greetings").json())

    application = create_test_app(AppModule)
    with TestClient(cast(Any, application)) as client:
        print(client.get("/greetings").json())
        with override_provider(
            application, GreetingService, FakeGreetingService("from override_provider")
        ):
            print(client.get("/greetings").json())
        print(client.get("/greetings").json())