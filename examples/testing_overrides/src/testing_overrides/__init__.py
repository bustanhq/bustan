"""Testing override example package."""

from __future__ import annotations

import asyncio
from typing import Any, cast

from starlette.testclient import TestClient

from bustan import Application, create_app
from bustan.testing import CompiledTestingModule, create_test_app, create_testing_module

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


def compile_with_fake_greeting(message: str) -> CompiledTestingModule:
    """Build and start an application whose greeting service is replaced.

    An override belongs to bootstrap, so the replacement is registered while the
    testing module is being assembled and the application starts with it already in
    place. Compiling is asynchronous because startup is: the application runs the same
    startup a served one does.
    """

    return asyncio.run(
        create_testing_module(AppModule)
        .override_provider(GreetingService)
        .use_value(FakeGreetingService(message))
        .compile()
    )


def demo() -> None:
    """Print the response each supported override pattern produces."""

    replaced_at_creation = create_test_app(
        AppModule,
        provider_overrides={GreetingService: FakeGreetingService("from create_test_app")},
    )
    with TestClient(cast(Any, replaced_at_creation)) as client:
        print(client.get("/greetings").json())

    compiled = compile_with_fake_greeting("from create_testing_module")
    try:
        with compiled.create_client() as client:
            print(client.get("/greetings").json())
    finally:
        asyncio.run(compiled.close())

    untouched = create_test_app(AppModule)
    with TestClient(cast(Any, untouched)) as client:
        print(client.get("/greetings").json())
