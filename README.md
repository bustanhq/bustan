# Bustan

Bustan is a modular architecture engine for building scalable, testable ASGI applications. Inspired by NestJS, it gives Python projects explicit composition boundaries, constructor injection, lifecycle hooks, and a predictable request pipeline while still exposing the underlying platform directly.

The HTTP transport sits behind an adapter port. Bustan ships two adapters - Starlette, which is the default, and a raw ASGI one that needs no third-party web framework - and both are held to the same conformance suite. An application that serves no HTTP at all needs neither.

## Why Bustan

- Use modules as real composition boundaries instead of ad hoc import graphs.
- Keep controllers thin and move business logic into DI-managed providers.
- Apply guards, pipes, interceptors, and exception filters in a predictable order.
- Keep direct access to the underlying platform through the public `Application` wrapper.
- Test applications with focused module builders, route snapshots, and provider overrides.

## Status

> [!IMPORTANT]
> Versions `1.0.0` and `1.0.1` were unintentionally released during CI/CD setup. Treat them as early alpha orphans. The first production-ready, non-alpha release target remains `2.0.0`.

- The release being prepared is the `version` field in `pyproject.toml`; read it there rather than from a list that cannot notice it moved.
- The supported Python floor is currently `>=3.13`.
- Compatibility promises apply only to `bustan`, `bustan.errors`, and `bustan.testing`. [docs/reference/stability.md](docs/reference/stability.md) is the authority on what is inside that boundary, and the export sets derive from it.
- Internal modules such as `bustan.kernel.*`, `bustan.app.*`, `bustan.runtime.*` and `bustan.adapters.*` are implementation details and may be restructured without notice.

## Installation

### Work On The Repository From Source

```bash
uv sync --group dev
```

That installs the framework, tests, linting, typing tools, and the local CLI entry point.

### Start A New Application

```bash
uv init --package my-app
cd my-app
uv add 'bustan[starlette]'
uv add --dev pytest ruff ty
uv run bustan init
```

### Install The Published Package

An application that serves HTTP over the shipped Starlette adapter installs the `starlette` extra:

```bash
uv add 'bustan[starlette]'
# or
pip install 'bustan[starlette]'
```

Plain `bustan` installs no web server. That is the install for using the framework as a library: modules, providers, and dependency injection resolved through `create_app_context`, with no HTTP served.

```bash
uv add bustan
# or
pip install bustan
```

## Quickstart

The recommended quickstart uses the CLI scaffold instead of hand-writing the first package layout.

```bash
uv init --package my-app
cd my-app
uv add 'bustan[starlette]'
uv add --dev pytest ruff ty
uv run bustan init
```

That creates a package like this:

```text
src/
  my_app/
    __init__.py
    app_module.py
    app_controller.py
    app_service.py
tests/
  my_app/
    test_app_controller.py
    test_app_module.py
    test_app_service.py
```

The scaffold also adds `start` and `dev` script entries when `pyproject.toml` does not already define them. Run the generated app with:

```bash
uv run dev
```

Then call the root route:

```bash
curl http://127.0.0.1:3000/
```

Expected response:

```json
{"message":"Hello from My App"}
```

For the full walkthrough, generated file contents, and first test, see [docs/tutorials/first-app.md](docs/tutorials/first-app.md).

## What You Get Today

Composition and injection:

- module discovery, validation, and export-based provider visibility
- constructor injection for providers and controllers, with the scope rules enforced while the application is built rather than on the request that trips them
- singleton, request, durable and transient lifetimes, plus request-scoped controllers
- dynamic modules, `ConfigurableModuleBuilder`, and module-level configuration

Serving requests:

- controller route compilation onto either shipped adapter, behind one adapter port
- inferred and explicit request binding with `Annotated[...]` markers
- response coercion for the neutral `HttpResponse`, the transport's own responses, dataclasses, iterators, `Path`, and `None`
- route middleware, guards, pipes, interceptors, and exception filters, in a documented order
- automatic Pydantic validation in `validation_mode="auto"`
- an `HttpException` family covering the fifteen statuses an application answers with, rendered as problem details
- finite request limits - body bytes, upload bytes, upload files, wall clock, synchronous handler threads - that an application serves under whether or not it configures them

Running in production:

- module and provider lifecycle hooks wired through the serving adapter's lifespan
- graceful shutdown: readiness turns negative, in-flight requests drain, teardown hooks run with the signal's name, the port is released
- a health module with liveness and readiness reporting
- correlation ids, request timing, and pluggable metrics and tracing sinks
- config, OpenAPI, throttling, CORS, and testing helpers

Tooling:

- `Application` and `ApplicationContext` bootstrapping
- route snapshots, route diffs, and runtime discovery support
- a CLI: `bustan init`, `doctor`, `graph`, `routes`, `config`, and `governance`

## Supported Public API

The current compatibility boundary is intentionally small.

Stable import paths:

- `bustan`
- `bustan.errors`
- `bustan.testing`

Example supported imports:

```python
from bustan import Application, Controller, Get, Injectable, Module, create_app, create_app_context
from bustan.errors import ProviderResolutionError
from bustan.testing import create_test_app, create_testing_module
```

The generated reference for those stable modules lives in [docs/reference/api.md](docs/reference/api.md).

## Guides

- [docs/README.md](docs/README.md)
- [docs/tutorials/first-app.md](docs/tutorials/first-app.md)
- [docs/reference/routing.md](docs/reference/routing.md)
- [docs/reference/request-pipeline.md](docs/reference/request-pipeline.md)
- [docs/explanation/request-scope.md](docs/explanation/request-scope.md)
- [docs/reference/lifecycle.md](docs/reference/lifecycle.md)
- [docs/reference/adapters.md](docs/reference/adapters.md)
- [docs/reference/cli.md](docs/reference/cli.md)
- [docs/how-to/run-benchmarks.md](docs/how-to/run-benchmarks.md)
- [docs/reference/stability.md](docs/reference/stability.md)
- [docs/reference/versioning.md](docs/reference/versioning.md)
- [docs/reference/errors.md](docs/reference/errors.md)
- [docs/explanation/comparisons.md](docs/explanation/comparisons.md)

## Open Source Project Docs

- [CONTRIBUTING.md](CONTRIBUTING.md)
- [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
- [SECURITY.md](SECURITY.md)
- [GOVERNANCE.md](GOVERNANCE.md)
- [CHANGELOG.md](CHANGELOG.md)
- [docs/how-to/cut-a-release.md](docs/how-to/cut-a-release.md)

## Examples

The repository includes focused examples beyond the starter app. Each example now mirrors the standalone mini-project layout used by `.bustan/mini`: its own `README.md`, `pyproject.toml`, `src/`, and `tests/`.

- [examples/README.md](examples/README.md)
- [examples/blog_api/README.md](examples/blog_api/README.md): reference-style blog API with feature modules and request-scoped actor state
- [examples/multi_module_app/README.md](examples/multi_module_app/README.md): provider exports crossing module boundaries
- [examples/graph_inspection/README.md](examples/graph_inspection/README.md): supported runtime inspection with `DiscoveryService` and route snapshots
- [examples/request_scope_pipeline_app/README.md](examples/request_scope_pipeline_app/README.md): request-local state shared across guards, interceptors, and a request-scoped controller
- [examples/testing_overrides/README.md](examples/testing_overrides/README.md): test-time provider overrides with `bustan.testing`
- [examples/dynamic_module_usage/README.md](examples/dynamic_module_usage/README.md): configurable dynamic module registration

Run one with:

```bash
cd examples/blog_api
uv sync --group dev
uv run python -m blog_api.app
```

## Testing Utilities

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

## Support

Use GitHub Issues for questions, bug reports, feature requests, and adoption feedback:

- https://github.com/bustanhq/bustan/issues

Do not use public issues for sensitive security reports. Follow the private disclosure guidance in [SECURITY.md](SECURITY.md).

## Roadmap

Near-term priorities for the first production-ready release (`2.0.0`):

- stabilize the PascalCase public contract
- keep the scaffold, README, guides, and checked-in examples aligned
- widen runtime support beyond Python `3.13`
- collect external adopter feedback before calling any release stable
- publish a fuller reference app or companion tutorial repository

## Development

Install hooks once after cloning if you want local pre-commit and pre-push checks:

```bash
uv run lefthook install
```

For contributor expectations, see [CONTRIBUTING.md](CONTRIBUTING.md).

Run the main checks with:

```bash
uv sync --group dev --frozen
uv run ruff format --check . && uv run ruff check .
uv run ty check src tests scripts
uv run pytest --cov=bustan --cov-report=term-missing
uv run python scripts/check_layering.py
uv run python scripts/conformance_matrix.py
uv run python scripts/generate_api_reference.py --check
uv run python scripts/check_markdown_links.py
uv run python scripts/run_examples.py
```

`conformance_matrix.py` runs the adapter conformance suite over both shipped adapters and fails when they answer any case differently; `check_layering.py` fails when the kernel reaches into a transport.

If you change public docstrings in the stable modules, regenerate the API reference with:

```bash
uv run python scripts/generate_api_reference.py
```

## Project Direction

Bustan is opinionated about application structure, not about hiding the underlying platform or competing on benchmark claims.

If you want a small ASGI core with explicit module boundaries, DI-managed services, lifecycle hooks, and a predictable request pipeline, that is the target use case for Bustan.

