# Test An Application

`bustan.testing` is the supported entry point for test-time application assembly: start an
application with providers replaced, or build a throwaway module for one test.

For what is inside the supported boundary, see [Stability](../reference/stability.md).

Use `create_test_app()` to start an app with one or more providers replaced:

```python
from typing import Any, cast

from bustan import Controller, Get, Injectable, Module
from bustan.testing import AsgiTestClient, create_test_app


@Injectable()
class GreetingService:
    def greet(self) -> str:
        return "hello from the real service"


class FakeGreetingService:
    def greet(self) -> str:
        return "hello from the fake"


@Controller("/greetings")
class GreetingsController:
    def __init__(self, greeting_service: GreetingService) -> None:
        self.greeting_service = greeting_service

    @Get("/")
    def index(self) -> dict[str, str]:
        return {"message": self.greeting_service.greet()}


@Module(controllers=[GreetingsController], providers=[GreetingService])
class AppModule:
    pass


application = create_test_app(
    AppModule,
    provider_overrides={GreetingService: FakeGreetingService()},
)

with AsgiTestClient(cast(Any, application)) as client:
    print(client.get("/greetings").json())
```

```text
{'message': 'hello from the fake'}
```

Use `create_testing_module()` when you want the test to assemble and start the application itself:

```python
import asyncio

from bustan import Controller, Get, Injectable, Module
from bustan.testing import create_testing_module


@Injectable()
class GreetingService:
    def greet(self) -> str:
        return "hello from the real service"


class FakeGreetingService:
    def greet(self) -> str:
        return "hello from the fake"


@Controller("/greetings")
class GreetingsController:
    def __init__(self, greeting_service: GreetingService) -> None:
        self.greeting_service = greeting_service

    @Get("/")
    def index(self) -> dict[str, str]:
        return {"message": self.greeting_service.greet()}


@Module(controllers=[GreetingsController], providers=[GreetingService])
class AppModule:
    pass


async def main() -> None:
    compiled = await (
        create_testing_module(AppModule)
        .override_provider(GreetingService)
        .use_value(FakeGreetingService())
        .compile()
    )
    try:
        # The client is synchronous. Used as a context manager it runs the application
        # on a loop of its own, which is what lets it be driven from inside this one.
        with compiled.create_client() as client:
            print(client.get("/greetings").json())
    finally:
        await compiled.close()


asyncio.run(main())
```

```text
{'message': 'hello from the fake'}
```

Both register the replacement before the application starts, which is the only point at which an override is honoured in full. An override does not stand beside the provider it replaces; it replaces it for the whole application, including the singletons already built from it. A running application therefore refuses one and says so, rather than swapping a dependency that everything already holding it would keep.

Use `create_test_module()` when you want a temporary module class for an isolated test instead of declaring one manually.

## Share Setup With A Fixture

Every example above builds an application inline. That is right for two tests and wrong for twenty:
once a suite has shared setup - a store to open, a token to send - it belongs in one place.

```python
# tests/conftest.py
from __future__ import annotations

from collections.abc import Iterator

import pytest
from bustan.testing import AsgiTestClient
from my_app import build_application


@pytest.fixture
def client() -> Iterator[AsgiTestClient]:
    with AsgiTestClient(build_application()) as running_client:
        yield running_client


@pytest.fixture
def token() -> dict[str, str]:
    return {"authorization": "Bearer local-development-token"}
```

Yielding inside the `with` block is what matters: each test gets an application that has run its
bootstrap hooks, and the teardown hooks run when the test ends, however it ends.

**Almost nothing in a suite needs to be async.** `AsgiTestClient` is synchronous and drives the
application on a loop of its own, so no async plugin is needed and none is assumed. The exception is
compiling a testing module directly, which returns a coroutine; `asyncio.run()` covers it.

A worked suite built this way is
[`examples/link_shortener`](../../examples/link_shortener/), whose tests are named for the promises they
check.
