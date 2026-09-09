# A Datastore And A Readiness Probe

**Where you are.** You finished [Configuration End To End](configuration-end-to-end.md), and
`bustan config` prints the values your application resolved.

By the end of this, tasks will survive a restart, the connection will be opened once and disposed
once, and `/health/ready` will tell the truth about whether the application can serve.

## The Store, And Where Its Lifetime Belongs

A connection is not built in a constructor. A constructor cannot await, and a failure in one is
harder to attribute than a failure in a named startup step. The framework calls hooks on your
providers for exactly this.

Add `DATABASE_PATH` to `settings.py` and to `.env`:

```python
    DATABASE_PATH: str = Field(min_length=1)
```

```bash
DATABASE_PATH=./tasks.db
```

Create `src/my_app/task_store.py`:

```python
from __future__ import annotations

import sqlite3

from bustan import ConfigService, Injectable


@Injectable()
class TaskStore:
    def __init__(self, config: ConfigService) -> None:
        self._path = str(config.get_or_throw("DATABASE_PATH"))
        self._connection: sqlite3.Connection | None = None

    async def on_application_bootstrap(self) -> None:
        self._connection = sqlite3.connect(self._path, check_same_thread=False)
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS tasks ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, done INTEGER NOT NULL)"
        )
        self._connection.commit()

    async def on_module_destroy(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    @property
    def connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("the task store is not open; the application has not started")
        return self._connection

    def is_answering(self) -> bool:
        if self._connection is None:
            return False
        try:
            self._connection.execute("SELECT 1").fetchone()
        except sqlite3.Error:
            return False
        return True
```

`sqlite3` because it needs no installation and no service, and because the shape is what matters: a
handle opened once, disposed once, and asked whether it still works. A real deployment swaps it for
a pool such as `asyncpg`; the hooks, the readiness check and everything above this class are
unchanged.

`check_same_thread=False` is required rather than convenient. A synchronous handler runs in a worker
thread while the event loop that opened the connection runs in another, and sqlite3 refuses that by
default.

### A Word On `async def`

Those two hooks are `async def` and nothing in them awaits. That is fine, and it is the first place
the question comes up, so: the framework runs your application on an event loop, and awaits any hook
that returns a coroutine. Declaring them `async` costs nothing and means you can await a real pool
later without changing the signature. The full ordering of hooks is in
[the lifecycle reference](../reference/lifecycle.md).

## Give The Store Its Own Module

The last two tutorials put a provider in the module that used it. This one is used by two, so it
gets a module of its own.

Create `src/my_app/store_module.py`:

```python
from bustan import Module

from .task_store import TaskStore


@Module(providers=[TaskStore], exports=[TaskStore])
class StoreModule:
    pass
```

If you skip this and declare `TaskStore` in the root module instead, the application refuses to
start:

```text
TasksRepository.__init__ parameter 'store' needs TaskStore, which TasksModule cannot see.
Declare it in that module, import a module that exports it, or give the parameter a default
```

That is worth causing once. A provider in the root module is not visible to a feature module, and
the refusal says so and names the three ways out. Modules are boundaries, and the framework enforces
it while the application is built rather than on the request that would have failed.

## Read And Write Through It

Create `src/my_app/tasks/tasks_repository.py`:

```python
from __future__ import annotations

from bustan import Injectable

from ..task_store import TaskStore
from .models import Task


@Injectable()
class TasksRepository:
    def __init__(self, store: TaskStore) -> None:
        self._store = store

    def list_tasks(self, limit: int) -> list[Task]:
        rows = self._store.connection.execute(
            "SELECT id, title, done FROM tasks ORDER BY id LIMIT ?", (limit,)
        ).fetchall()
        return [Task(id=row[0], title=row[1], done=bool(row[2])) for row in rows]

    def read_task(self, task_id: int) -> Task | None:
        row = self._store.connection.execute(
            "SELECT id, title, done FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        return None if row is None else Task(id=row[0], title=row[1], done=bool(row[2]))

    def create_task(self, title: str, done: bool) -> Task:
        connection = self._store.connection
        cursor = connection.execute(
            "INSERT INTO tasks (title, done) VALUES (?, ?)", (title, int(done))
        )
        connection.commit()
        return Task(id=int(cursor.lastrowid or 0), title=title, done=done)
```

Then `TasksService` delegates instead of holding a list:

```python
@Injectable()
class TasksService:
    def __init__(self, repository: TasksRepository, config: ConfigService) -> None:
        self._repository = repository
        self._page_size = int(config.get("PAGE_SIZE", 20))

    def list_tasks(self) -> list[Task]:
        return self._repository.list_tasks(self._page_size)

    def read_task(self, task_id: int) -> Task | None:
        return self._repository.read_task(task_id)

    def create_task(self, payload: CreateTaskPayload) -> Task:
        return self._repository.create_task(payload.title, payload.done)
```

The controller does not change at all. That is what the service boundary bought.

Update `TasksModule` to import the store and declare the repository:

```python
@Module(
    imports=[StoreModule],
    controllers=[TasksController],
    providers=[TasksService, TasksRepository],
    exports=[TasksService],
)
class TasksModule:
    pass
```

`TasksRepository` is not exported. It is this module's business, and nothing outside should reach a
database through it.

## Make Readiness Tell The Truth

An application that is running but cannot reach its store should not be sent traffic. That is what
readiness is for, and it is a different question from liveness, which asks only whether the process
is worth keeping alive. [The two probes](../how-to/observe-an-application.md#the-two-probes-answer-different-questions)
explains why conflating them causes restart loops.

Create `src/my_app/store_indicator.py`:

```python
from __future__ import annotations

from bustan import HealthIndicatorResult, HealthService, Injectable

from .task_store import TaskStore


@Injectable()
class TaskStoreIndicator:
    name = "task-store"

    def __init__(self, store: TaskStore) -> None:
        self._store = store

    async def check(self) -> HealthIndicatorResult:
        if self._store.is_answering():
            return HealthIndicatorResult.up()
        return HealthIndicatorResult.down("the task store is not answering")


@Injectable()
class HealthWiring:
    def __init__(self, health: HealthService, indicator: TaskStoreIndicator) -> None:
        self._health = health
        self._indicator = indicator

    def on_module_init(self) -> None:
        self._health.register_readiness(self._indicator)
```

The `detail` crosses a trust boundary: anything that can reach the probe reads it. Say what is wrong
in your own words, and never put a path, a driver message or a credential in there.

Import the health module and declare both providers in `app_module.py`:

```python
from bustan import ConfigModule, HealthModule, Module

from .store_indicator import HealthWiring, TaskStoreIndicator
from .store_module import StoreModule


@Module(
    imports=[
        ConfigModule.for_root(env_file=".env", validation_schema=Settings),
        HealthModule.for_root(),
        StoreModule,
        TasksModule,
    ],
    controllers=[AppController],
    providers=[AppService, TaskStoreIndicator, HealthWiring],
)
class AppModule:
    pass
```

Registering from `on_module_init` matters. That stage runs before anything can report the
application started, so the indicator is already being consulted the first time readiness could be
true.

## Drive It

```bash
uv run dev
curl -X POST http://127.0.0.1:3000/tasks/ -H 'content-type: application/json' -d '{"title":"Persist me"}'
```

Stop it, start it again, and read the list. The task is still there.

```bash
curl http://127.0.0.1:3000/health/ready
```

```json
{"status":"up","checks":{"lifecycle":{"status":"up","detail":null},
 "task-store":{"status":"up","detail":null}}}
```

## A Fixture, Now That There Is Something To Share

Three tests each building an application inline was repetition. Four tests that also need a store
open is shared setup, so it earns a `conftest.py`.

Create `tests/conftest.py`:

```python
from __future__ import annotations

from collections.abc import Iterator

import pytest
from bustan.testing import AsgiTestClient
from my_app import build_application


@pytest.fixture
def client() -> Iterator[AsgiTestClient]:
    with AsgiTestClient(build_application()) as running_client:
        yield running_client
```

Every test now takes `client` and starts from an application that has run its bootstrap hooks and
will run its teardown ones:

```python
def test_readiness_reports_the_store(client: AsgiTestClient) -> None:
    checks = client.get("/health/ready").json()["checks"]
    assert checks["task-store"]["status"] == "up"
```

Note what is not here: no async test function and no async plugin. `AsgiTestClient` is synchronous
and drives the application on a loop of its own, so almost nothing in a suite needs to be async.
More patterns are in [Test An Application](../how-to/test-an-application.md).

## Next

Anyone can create a task. Next: [Before The Handler Runs](before-the-handler-runs.md).
