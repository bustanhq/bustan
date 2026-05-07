# First App

This walkthrough builds a small Bustan application using the CLI scaffold and then extends it with a focused test.

## Create the Project

```bash
uv init --package my-app
cd my-app
uv add bustan
uv add --dev ty ruff
uv run bustan init
```

`bustan init` reads the project name from `pyproject.toml` and writes the following files:

```
src/my_app/
    __init__.py          # bootstrap, main(), dev()
    app_module.py
    app_controller.py
    app_service.py
tests/my_app/
    __init__.py
    test_app_controller.py
    test_app_module.py
    test_app_service.py
```

It also adds `start` and `dev` script entries to `pyproject.toml`:

```toml
[project.scripts]
start = "my_app:main"
dev   = "my_app:dev"
```

## Application Code

The generated files look like this:

**`app_service.py`**
```python
from bustan import Injectable

@Injectable()
class AppService:
    def get_message(self) -> dict[str, str]:
        return {"message": "Hello from My App"}
```

**`app_controller.py`**
```python
from bustan import Controller, Get
from .app_service import AppService

@Controller("/")
class AppController:
    def __init__(self, app_service: AppService):
        self.app_service = app_service

    @Get("/")
    def get_message(self) -> dict[str, str]:
        return self.app_service.get_message()
```

**`app_module.py`**
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

**`__init__.py`**
```python
import asyncio
from bustan import create_app
from .app_module import AppModule

async def bootstrap(reload: bool = False):
    app = create_app(AppModule)
    await app.listen(port=3000, reload=reload)

def main():
    asyncio.run(bootstrap())

def dev():
    asyncio.run(bootstrap(reload=True))
```

## Run It

```bash
uv run dev
```

Call the route:

```bash
curl http://127.0.0.1:3000/
```

Expected response:

```json
{"message": "Hello from My App"}
```

## Test It

Use `bustan.testing.create_test_app()` with Starlette's `TestClient`:

```python
from starlette.testclient import TestClient
from bustan.testing import create_test_app
from my_app.app_module import AppModule

def test_get_message_returns_200() -> None:
    app = create_test_app(AppModule)
    with TestClient(app) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "Hello from My App"}
```

When you want to replace a provider:

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

## What This Example Covers

- `@Injectable()` marks a DI-managed provider.
- `@Controller` groups related routes behind one prefix.
- `@Module` is the composition boundary that tells bustan what to wire.
- `create_app()` turns the root module into a fully-configured ASGI application.
- `app.listen()` starts the server; `reload=True` enables hot-reload for development.
- `bustan.testing` lets you swap providers without mutating global state.
