# Configuration End To End

**Where you are.** You finished [A Resource With Three Routes](a-resource-with-three-routes.md), and
`POST /tasks/` answers `201` while `GET /tasks/999` answers `404`.

By the end of this, every setting will live outside the source, be validated once while the
application is built, and be readable from any provider. You will also cause a startup refusal on
purpose and read it, because the first one you meet should not be a real one.

## State What The Application Needs

A schema turns a missing or malformed setting into a refusal at startup, where one person reads it,
rather than an `AttributeError` on the first request that needed it.

Create `src/my_app/settings.py`:

```python
from __future__ import annotations

from pydantic import BaseModel, Field


class Settings(BaseModel):
    model_config = {"extra": "ignore"}

    API_TOKEN: str = Field(min_length=8)
    PAGE_SIZE: int = Field(default=20, ge=1, le=100)
```

`extra: ignore` matters. The environment holds hundreds of variables that are nothing to do with
this application, and without it every one of them is an error.

## Supply The Values

Create `.env` beside `pyproject.toml`:

```bash
API_TOKEN=tutorial-secret-token
PAGE_SIZE=20
```

Add it to `.gitignore`. A `.env` is for local development; production supplies the same names as
real environment variables, and an environment variable wins over the file.

## Load It Once

In `src/my_app/app_module.py`:

```python
from bustan import ConfigModule, Module

from .app_controller import AppController
from .app_service import AppService
from .settings import Settings
from .tasks.tasks_module import TasksModule


@Module(
    imports=[
        ConfigModule.for_root(env_file=".env", validation_schema=Settings),
        TasksModule,
    ],
    controllers=[AppController],
    providers=[AppService],
)
class AppModule:
    pass
```

`ConfigModule.for_root` is global by default, so every module can inject `ConfigService` without
importing it. That is deliberate and it is the exception, not the pattern. Configuration is
genuinely needed everywhere; almost nothing else is, and reaching for `is_global` to solve an import
problem dissolves the boundaries the last tutorial taught. [Layering](../explanation/layering.md)
explains why direction matters.

## Read It Where It Is Used

Change `TasksService` in `src/my_app/tasks/tasks_service.py`:

```python
from bustan import ConfigService, Injectable


@Injectable()
class TasksService:
    def __init__(self, config: ConfigService) -> None:
        self._page_size = int(config.get("PAGE_SIZE", 20))
        self._tasks: list[Task] = []
        self._next_id = 1

    def list_tasks(self) -> list[Task]:
        return list(self._tasks)[: self._page_size]
```

`get` takes a default and `get_or_throw` refuses when a value is absent. Use `get_or_throw` for
anything the application genuinely cannot run without, so the failure names the setting instead of
surfacing as a `None` three layers away.

## Cause The Refusal On Purpose

Shorten the token in `.env` so it breaks the schema:

```bash
API_TOKEN=short
```

```bash
uv run dev
```

The application does not start:

```text
pydantic_core._pydantic_core.ValidationError: 1 validation error for Settings
API_TOKEN
  String should have at least 8 characters
```

That is the whole point of a schema. The application refuses to run with a setting it cannot use,
and it says which one and why, before a single request arrives. Put the real value back.

Meeting this message for the first time as a deliberate exercise costs a minute. Meeting it for the
first time at three in the morning costs rather more.

## Check What The Application Actually Resolved

```bash
uv run bustan config my_app.app_module:AppModule
```

```text
config (2)
key         value
----------  ----------
API_TOKEN   [redacted]
PAGE_SIZE   20
```

`API_TOKEN` reads as a credential, so it is withheld rather than printed. That is the command
working, not failing. It prints the values as the application sees them, after the file and the
environment have been merged. It is the fastest way to answer "is it reading my `.env` at all", and it is worth running
before you write code that depends on a value. Two limits on what it prints are in
[the CLI reference](../reference/cli.md#bustan-config).

## Prove The Environment Wins

```bash
PAGE_SIZE=1 uv run bustan config my_app.app_module:AppModule
```

`PAGE_SIZE` prints as `1`, not the `20` in the file. That is the mechanism a deployment uses: the same
image, a different environment, no rebuild. Nothing in
[Deploy An Application](../how-to/deploy.md) works any other way.

## Next

Tasks still live in a list that empties on restart. Next:
[A Datastore And A Readiness Probe](a-datastore-and-a-readiness-probe.md).
