# Links That Survive A Restart

Make a link, restart the server, and it is gone. Your links live in a dictionary on an object that
dies with the process.

This tutorial puts them in a database. Along the way you will meet the two hooks that let a provider
own something with a lifetime, and you will teach the application to admit when it cannot serve.

## Where A Connection Belongs

The obvious place to open a database is the constructor. It is the wrong place, for two reasons you
will hit sooner than you expect.

A constructor cannot `await`, and real database drivers are asynchronous. And a constructor runs
whenever the framework happens to build the object, which is not a moment you control or can name in
a log. "Failed while constructing LinksRepository" is a worse thing to read at 3am than "failed
during startup".

Providers can implement lifecycle hooks instead. The framework calls them at named points, in order,
and awaits them if they return a coroutine. Create `src/my_app/link_store.py`:

```python
from __future__ import annotations

import sqlite3

from bustan import ConfigService, Injectable


@Injectable()
class LinkStore:
    def __init__(self, config: ConfigService) -> None:
        self._path = str(config.get_or_throw("DATABASE_PATH"))
        self._connection: sqlite3.Connection | None = None

    async def on_application_bootstrap(self) -> None:
        self._connection = sqlite3.connect(self._path, check_same_thread=False)
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS links ("
            "code TEXT PRIMARY KEY, url TEXT NOT NULL, visits INTEGER NOT NULL DEFAULT 0)"
        )
        self._connection.commit()

    async def on_module_destroy(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    @property
    def connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("the link store is not open; the application has not started")
        return self._connection
```

The constructor still runs, and all it does is read a setting. The work happens in
`on_application_bootstrap`, which runs once while the application starts, and is undone in
`on_module_destroy`, which runs once while it stops. Neither is a place you call yourself.

`get_or_throw` rather than `get` this time. A missing code length has a sensible default; a missing
database path does not, and you would rather be told which setting is absent than watch it connect
to the string "None".

Add `DATABASE_PATH` to `Settings` and to `.env`:

```python
    DATABASE_PATH: str = Field(min_length=1)
```

```bash
DATABASE_PATH=./links.db
```

### Two Details That Will Bite You

`check_same_thread=False` is required rather than tidy. Your handlers are synchronous `def` methods,
so the framework runs them in a worker thread while the event loop that opened this connection runs
in another. Without that flag sqlite3 refuses to be used across the two, and the error does not
mention threads in a way that helps.

The two hooks are `async def` and nothing in them awaits. That is fine and it is on purpose. The
framework runs your application on an event loop and awaits any hook that hands back a coroutine, so
declaring them async costs nothing today and means swapping sqlite3 for `asyncpg` later changes the
body of the method and not its signature. The full list of hooks and the order they run in is in
[the lifecycle reference](../reference/lifecycle.md).

## A Module Of Its Own, And A Refusal If You Skip It

`LinkStore` is used by the links feature and, shortly, by the health check. Two consumers means it
gets its own module. Create `src/my_app/store_module.py`:

```python
from bustan import Module

from .link_store import LinkStore


@Module(providers=[LinkStore], exports=[LinkStore])
class StoreModule:
    pass
```

Before you import it anywhere, do this deliberately: declare `LinkStore` in the **root** module's
`providers` list instead, and start the application.

```text
LinksRepository.__init__ parameter 'store' needs LinkStore, which LinksModule cannot see.
Declare it in that module, import a module that exports it, or give the parameter a default
```

It will not start. This is the `exports` list from tutorial two doing its job: a provider declared in
the root module is not visible inside a feature module, because modules are boundaries rather than
folders. The message names the class, the parameter, the module that cannot see it, and the three
ways out.

Notice when this happened. Not on a request, not under load — while the application was being built,
before it bound a port. Bustan resolves the whole graph at startup precisely so that wiring mistakes
are a refusal you read once rather than a `500` somebody else finds.

Take the fix the message offers: `imports=[StoreModule]` on `LinksModule`.

## Reading And Writing Through It

Split the storage out of `LinksService` into a repository. Create
`src/my_app/links/links_repository.py`:

```python
from __future__ import annotations

import sqlite3

from bustan import Injectable

from ..link_store import LinkStore
from .models import Link


@Injectable()
class LinksRepository:
    def __init__(self, store: LinkStore) -> None:
        self._store = store

    def read_link(self, code: str) -> Link | None:
        row = self._store.connection.execute(
            "SELECT code, url, visits FROM links WHERE code = ?", (code,)
        ).fetchone()
        return None if row is None else Link(code=row[0], url=row[1], visits=row[2])

    def create_link(self, code: str, url: str) -> Link | None:
        connection = self._store.connection
        try:
            connection.execute(
                "INSERT INTO links (code, url, visits) VALUES (?, ?, 0)", (code, url)
            )
        except sqlite3.IntegrityError:
            return None
        connection.commit()
        return Link(code=code, url=url, visits=0)

    def count_visit(self, code: str) -> None:
        connection = self._store.connection
        connection.execute("UPDATE links SET visits = visits + 1 WHERE code = ?", (code,))
        connection.commit()
```

`create_link` returning `None` on a duplicate is the database telling you the code is taken.
`PRIMARY KEY` makes that a constraint the database enforces rather than a check you race against.

Add a `Link` dataclass to `models.py`:

```python
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Link:
    code: str
    url: str
    visits: int
```

Then `LinksService` delegates instead of holding a dictionary, and gains retry-on-collision:

```python
    def create_link(self, url: str) -> Link | None:
        for _ in range(5):
            code = "".join(secrets.choice(ALPHABET) for _ in range(self._code_length))
            link = self._repository.create_link(code, url)
            if link is not None:
                return link
        return None

    def follow_link(self, code: str) -> Link | None:
        link = self._repository.read_link(code)
        if link is not None:
            self._repository.count_visit(code)
        return link
```

Neither controller changes. That is what the service boundary bought you two tutorials ago.

Declare the repository in `LinksModule`'s providers, but do **not** export it. Nothing outside the
links feature should be reaching a database through it.

## Try It

```bash
uv run dev
curl -X POST http://127.0.0.1:3000/links/ -H 'content-type: application/json' \
  -d '{"url": "https://bustan.dev"}'
```

Stop the server with Ctrl-C. Start it again. Follow the code you were given.

It still works. There is a `links.db` file next to your `pyproject.toml` now, and you can open it
with `sqlite3 links.db "select * from links"` if you want to see the rows.

sqlite3 is here because it needs no service and no install, not because it is what you would deploy.
The shape is the point: a handle opened once, disposed once, and asked whether it still works. Swap
in a connection pool and the hooks, the readiness check below and everything above this class are
unchanged.

## Telling The Truth About Whether You Can Serve

Here is a failure mode worth caring about. Your application is running, the port is open, and the
database has gone away. Every request returns a `500`, and any load balancer in front of you keeps
sending traffic, because as far as it can tell the process is fine.

That is what readiness is for. Add a way to ask the store whether it still works:

```python
    def is_answering(self) -> bool:
        if self._connection is None:
            return False
        try:
            self._connection.execute("SELECT 1").fetchone()
        except sqlite3.Error:
            return False
        return True
```

Then report it. Create `src/my_app/store_indicator.py`:

```python
from __future__ import annotations

from bustan import HealthIndicatorResult, HealthService, Injectable

from .link_store import LinkStore


@Injectable()
class LinkStoreIndicator:
    name = "link-store"

    def __init__(self, store: LinkStore) -> None:
        self._store = store

    async def check(self) -> HealthIndicatorResult:
        if self._store.is_answering():
            return HealthIndicatorResult.up()
        return HealthIndicatorResult.down("the link store is not answering")


@Injectable()
class HealthWiring:
    def __init__(self, health: HealthService, indicator: LinkStoreIndicator) -> None:
        self._health = health
        self._indicator = indicator

    def on_module_init(self) -> None:
        self._health.register_readiness(self._indicator)
```

`on_module_init` runs earlier than `on_application_bootstrap`, before anything can report the
application as started. Registering there means the indicator is already being consulted the first
time readiness could possibly be true.

That `detail` string goes to anyone who can reach the probe, which in most deployments is anyone
inside the network. Say what is wrong in your own words. Never put the path, the driver's exception
or a connection string in there.

Import the health module and declare both providers in the root module:

```python
@Module(
    imports=[
        ConfigModule.for_root(env_file=".env", validation_schema=Settings),
        HealthModule.for_root(),
        StoreModule,
        LinksModule,
    ],
    providers=[LinkStoreIndicator, HealthWiring],
)
class AppModule:
    pass
```

```bash
curl http://127.0.0.1:3000/health/ready
```

```json
{"status":"up","checks":{"lifecycle":{"status":"up","detail":null},
 "link-store":{"status":"up","detail":null}}}
```

There is a second probe at `/health/live`, and the difference matters. Liveness asks whether the
process is worth keeping alive; readiness asks whether it should be sent traffic. Wire a database
check to liveness and a database blip restarts your application, which does not help and usually
makes it worse. [The two probes](../how-to/observe-an-application.md#the-two-probes-answer-different-questions)
goes into it.

## A Fixture, Now That There Is Something To Share

Your tests each build an application inline. With a store to open that repetition is no longer just
noise, so give it a home. Create `tests/conftest.py`:

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

Yielding inside the `with` block is the part that matters: each test gets an application that has run
its bootstrap hooks, and the teardown hooks run when the test finishes, however it finishes.

Every test now takes `client` and drops four lines:

```python
def test_readiness_reports_the_store(client: AsgiTestClient) -> None:
    assert client.get("/health/ready").json()["checks"]["link-store"]["status"] == "up"
```

Point `DATABASE_PATH` at `:memory:` while testing so runs do not accumulate a file.

Notice there is no `async def` test and no async plugin. `AsgiTestClient` is synchronous and drives
the application on its own loop, so a suite almost never needs to be asynchronous. More patterns are
in [Test An Application](../how-to/test-an-application.md).

## Where This Leaves You

Links survive restarts, the connection is opened and closed at named points, and the application
tells the truth about whether it can serve.

Anyone on the internet can still create links on your shortener, which is the next problem:
[Deciding Who May Create A Link](before-the-handler-runs.md).
