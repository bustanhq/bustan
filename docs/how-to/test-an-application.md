# Test An Application

`bustan.testing` is the supported entry point for test-time application assembly: start an
application with providers replaced, or build a throwaway module for one test.

For what is inside the supported boundary, see [Stability](../reference/stability.md).

`bustan.testing` is the supported entry point for test-time application assembly.

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
