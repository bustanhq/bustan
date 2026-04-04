# First App

This walkthrough builds a small `star` application with one provider, one controller, one module, and one focused test.

## Application Code

```python
from star import controller, create_app, get, injectable, module


@injectable
class GreetingService:
    def greet(self) -> dict[str, str]:
        return {"message": "hello from star"}


@controller("/hello")
class GreetingController:
    def __init__(self, greeting_service: GreetingService) -> None:
        self.greeting_service = greeting_service

    @get("/")
    def read_greeting(self) -> dict[str, str]:
        return self.greeting_service.greet()


@module(
    controllers=[GreetingController],
    providers=[GreetingService],
    exports=[GreetingService],
)
class AppModule:
    pass


app = create_app(AppModule)
```

## Run It

```bash
uv run uvicorn app:app --reload
curl http://127.0.0.1:8000/hello
```

Expected response:

```json
{"message":"hello from star"}
```

## Test It

For a direct application smoke test, use Starlette's test client:

```python
from starlette.testclient import TestClient

from app import app


def test_read_greeting() -> None:
    with TestClient(app) as client:
        response = client.get("/hello")

    assert response.status_code == 200
    assert response.json() == {"message": "hello from star"}
```

When you want to replace providers in tests, use `star.testing.create_test_app()`:

```python
from star.testing import create_test_app


class FakeGreetingService:
    def greet(self) -> dict[str, str]:
        return {"message": "hello from a test double"}


application = create_test_app(
    AppModule,
    provider_overrides={GreetingService: FakeGreetingService()},
)
```

## What This Example Covers

- `@injectable` marks a DI-managed provider.
- `@controller` groups related routes behind one prefix.
- `@module` is the composition boundary that tells `star` what to wire.
- `create_app()` turns the root module into a Starlette application.
- `star.testing` lets you swap providers without mutating global state.