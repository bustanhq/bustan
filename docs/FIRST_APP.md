# First App

This walkthrough uses the current CLI scaffold, which is the recommended starting point for new Bustan projects. The scaffold produces the same package shape the checked-in examples now follow: an application package with `__init__.py`, a root module, a controller, a service, and focused tests.

## Create The Project

```bash
uv init --package my-app
cd my-app
uv add bustan
uv add --dev pytest ruff ty
uv run bustan init
```

`bustan init` reads `project.name` from `pyproject.toml`, normalizes it into a package name, and writes a runnable application skeleton.

Generated layout:

```text
src/
  my_app/
    __init__.py          # bootstrap(), main(), dev()
    app_module.py        # root module
    app_controller.py    # root controller
    app_service.py       # root provider
tests/
  my_app/
    __init__.py
    test_app_controller.py
    test_app_module.py
    test_app_service.py
```

If `pyproject.toml` does not already define console scripts, the scaffold also adds:

```toml
[project.scripts]
start = "my_app:main"
dev = "my_app:dev"
```

## Understand The Generated Files

`app_service.py` holds the first DI-managed provider:

```python
from bustan import Injectable


@Injectable()
class AppService:
    def get_message(self) -> dict[str, str]:
        return {"message": "Hello from My App"}
```

`app_controller.py` stays thin and delegates to the provider:

```python
from bustan import Controller, Get

from .app_service import AppService


@Controller("/")
class AppController:
    def __init__(self, app_service: AppService) -> None:
        self.app_service = app_service

    @Get("/")
    def get_message(self) -> dict[str, str]:
        return self.app_service.get_message()
```

`app_module.py` is the composition boundary that tells Bustan what to compile:

```python
from bustan import Module

from .app_controller import AppController
from .app_service import AppService


@Module(
    controllers=[AppController],
    providers=[AppService],
)
class AppModule:
    pass
```

`__init__.py` is the package entry point. It is where the `Application` wrapper is created and where the development scripts land:

```python
import asyncio

from bustan import create_app

from .app_module import AppModule


async def bootstrap(reload: bool = False) -> None:
    app = create_app(AppModule)
    await app.listen(port=3000, reload=reload)


def main() -> None:
    asyncio.run(bootstrap())


def dev() -> None:
    asyncio.run(bootstrap(reload=True))
```

## Run The App

Use the generated development entry point:

```bash
uv run dev
```

Or start without reload:

```bash
uv run start
```

Call the root route:

```bash
curl http://127.0.0.1:3000/
```

Expected response:

```json
{"message": "Hello from My App"}
```

## Add A First Test

The scaffold includes a controller test built around `bustan.testing.create_test_app()` and Starlette's `TestClient`:

```python
from starlette.testclient import TestClient

from bustan.testing import create_test_app

from my_app.app_module import AppModule


def test_get_message_returns_200_with_expected_payload() -> None:
    application = create_test_app(AppModule)
    with TestClient(application) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {"message": "Hello from My App"}
```

Run it with:

```bash
uv run pytest
```

## Replace Providers In Tests

When you need to replace a provider for one test or one application instance, use `bustan.testing` rather than mutating the container directly.

One-off replacement when creating the test app:

```python
from bustan.testing import create_test_app


class FakeAppService:
    def get_message(self) -> dict[str, str]:
        return {"message": "hello from a test double"}


application = create_test_app(
    AppModule,
    provider_overrides={AppService: FakeAppService()},
)
```

Scoped replacement against an existing application:

```python
from bustan.testing import override_provider


with override_provider(application, AppService, FakeAppService()):
    ...
```

## What This Flow Teaches

- `@Injectable()` marks a provider the container can construct and inject.
- `@Controller()` groups HTTP handlers under one prefix.
- `@Module()` defines imports, providers, exports, and controllers as one composition unit.
- `create_app()` returns the public `Application` wrapper, not a raw Starlette app.
- `app.listen()` is the supported runtime entry point for local serving.
- `bustan.testing` is the supported way to build test applications and apply overrides.

After this walkthrough, continue with [ROUTING.md](ROUTING.md) and [REQUEST_PIPELINE.md](REQUEST_PIPELINE.md) to understand how handlers bind inputs and how cross-cutting request logic is composed.
