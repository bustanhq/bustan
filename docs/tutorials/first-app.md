# First App

This walkthrough uses the current CLI scaffold, which is the recommended starting point for new
Bustan projects. It writes a root module, a controller and a service, a test for each of them, and
an entry-point module holding the `start` and `dev` entry points, and it declares in
`pyproject.toml` everything the project needs to run them, so one install command follows it and no
other.

**Before you start.** You need Python 3.13 or newer and [uv](https://docs.astral.sh/uv/), which
is the only supported package manager. `uv init` writes the floor from the interpreter it finds, so
on an older Python this fails at `uv add` with a resolver message rather than at import.

## Create The Project

```bash
uv init --package my-app
cd my-app
uv add bustan
uv run bustan init
uv sync
```

`bustan init` reads `project.name` from `pyproject.toml`, normalizes it into a package name, and
writes a runnable application under that name. It then names every path it wrote and every path it
left alone:

```text
Initialised Bustan app for package 'my_app'.
Wrote:
  src/my_app/app_main.py
  src/my_app/app_module.py
  src/my_app/app_controller.py
  src/my_app/app_service.py
  tests/my_app/test_app_controller.py
  tests/my_app/test_app_service.py
  tests/my_app/test_app_module.py
Kept:
  README.md
  src/my_app/__init__.py
Pass --force to replace a file that was kept.
```

Three lines after that name what it changed in `pyproject.toml`, and the last three are the next
steps: `uv sync`, `uv run start`, `uv run dev`.

**Kept means kept.** `uv init` has already written `README.md` and `src/my_app/__init__.py`, and a
file that is already there is reported rather than replaced. So the scaffold's own README never
reaches you on this path, and the package keeps the `__init__.py` uv wrote. Run `bustan init` again
and it reports the whole scaffold as kept and changes nothing, which is what makes it safe to
re-run; `bustan init --force` replaces a kept file instead, that `README.md` and that `__init__.py`
included.

**The manifest declares what the project needs.** Serving HTTP needs a transport, so the plain
`bustan` requirement `uv add` wrote becomes `bustan[starlette]`, the extra for the adapter this
package ships. Testing, linting and type-checking need tools, so a `dev` dependency group gains
pytest, ruff and ty. Running the app needs entry points, so `[project.scripts]` gains `start` and
`dev`. None of that is a second install step: the one `uv sync` above installs all of it.

Generated layout:

```text
src/
  my_app/
    __init__.py          # kept, as uv init wrote it
    app_main.py          # create_asgi_app(), bootstrap(), main(), dev()
    app_module.py        # root module
    app_controller.py    # root controller
    app_service.py       # root provider
tests/
  my_app/
    test_app_controller.py
    test_app_service.py
    test_app_module.py
```

The two scripts land in `[project.scripts]` beside the entry `uv init --package` already wrote
there, and only where that table does not declare them already:

```toml
[project.scripts]
start = "my_app.app_main:main"
dev = "my_app.app_main:dev"
```

Both name `app_main` rather than the package, so a package whose `__init__.py` came from somewhere
else keeps whatever `main` it already meant.

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
    def __init__(self, app_service: AppService):
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

`app_main.py` is the entry-point module. It is where the `Application` wrapper is created and where
both scripts land:

```python
import asyncio

import uvicorn
from bustan import Application, create_app

from .app_module import AppModule

HOST = "127.0.0.1"
PORT = 3000


def create_asgi_app() -> Application:
    """Return the application, which is itself the ASGI callable a server runs."""
    return create_app(AppModule)


async def bootstrap() -> None:
    await create_asgi_app().listen(port=PORT, host=HOST)


def main() -> None:
    asyncio.run(bootstrap())


def dev() -> None:
    # Reloading means owning the process: the server watches the source tree and, on
    # every change, starts a worker that imports the application again. That is why it
    # is handed the name of a factory rather than an application already built - a
    # built one belongs to the process that built it, and could not be rebuilt here.
    uvicorn.run(
        "my_app.app_main:create_asgi_app",
        factory=True,
        host=HOST,
        port=PORT,
        reload=True,
        reload_dirs=["src"],
    )
```

The two differ in who owns the process. `main` serves the application it just built, which is what
`app.listen()` does. `dev` hands uvicorn an import string instead and lets uvicorn's own supervisor
build the application after every restart. An adapter cannot reload for the same reason: it is
handed a live application object that a restart has no way to rebuild, so asking the Starlette
adapter for one is refused rather than quietly ignored.

## Run The App

Use the generated development entry point:

```bash
uv run dev
```

It watches `src/`, so editing a handler changes the next response without stopping anything.

Or start without reload:

```bash
uv run start
```

Call the root route, from a second terminal:

```bash
curl http://127.0.0.1:3000/
```

Expected response:

```json
{"message":"Hello from My App"}
```

## Add A First Test

The scaffold includes a controller test built around `bustan.testing.create_test_app()` and
`bustan.testing.AsgiTestClient`. The client ships with Bustan and pytest is in the `dev` group the
scaffold declared, so the generated test runs on what `uv sync` installed and needs no HTTP client
package of its own:

```python
from bustan.testing import AsgiTestClient, create_test_app

from my_app.app_module import AppModule


def test_get_message_returns_200_with_expected_payload() -> None:
    app = create_test_app(AppModule)
    with AsgiTestClient(app) as client:
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

Replacement in an application a test assembles for itself:

```python
from bustan.testing import create_testing_module


compiled = await (
    create_testing_module(AppModule)
    .override_provider(AppService)
    .use_value(FakeAppService())
    .compile()
)
```

Both replace the provider before the application starts, which is the only point at which a replacement is honoured in full. An override does not stand beside the provider it replaces; it replaces it for the whole application, including the singletons already built from it. A running application therefore refuses one and says so, rather than swapping a dependency that everything already holding it would keep. To serve requests against the replacement, build a client from the compiled module. It is the same `AsgiTestClient` the generated test uses:

```python
with compiled.create_client() as client:
    response = client.get("/")
```

## What This Flow Teaches

- `@Injectable()` marks a provider the container can construct and inject.
- `@Controller()` groups HTTP handlers under one prefix.
- `@Module()` defines imports, providers, exports, and controllers as one composition unit.
- `create_app()` returns the public `Application` wrapper, not a raw Starlette app.
- `app.listen()` is the supported runtime entry point for local serving, and is what `uv run start`
  calls.
- Reload belongs to a development server rather than to an adapter, which is why `uv run dev` runs
  uvicorn against the factory's import string.
- `bustan.testing` is the supported way to build test applications and apply overrides.

## Next

One route is not an application. Next: [A Resource With Three Routes](a-resource-with-three-routes.md),
which turns this into a resource that lists, reads and creates, answering the right status each time.

The series continues from there through configuration, a datastore, the request pipeline and OpenAPI.
The [tutorials index](../README.md#tutorials) lists all six.

For the binding rules and the pipeline in full, rather than as a path,
[the routing reference](../reference/routing.md) and
[the request pipeline reference](../reference/request-pipeline.md) are where they live.
