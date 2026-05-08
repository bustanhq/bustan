# Bustan

Bustan is a modular architecture engine for building scalable, testable ASGI applications. Inspired by NestJS, it gives Python projects explicit composition boundaries, constructor injection, lifecycle hooks, and a predictable request pipeline while still exposing the underlying platform directly.

Starlette is the default HTTP engine today. Bustan adds structure on top of it rather than replacing it.

## Why Bustan

- Use modules as real composition boundaries instead of ad hoc import graphs.
- Keep controllers thin and move business logic into DI-managed providers.
- Apply guards, pipes, interceptors, and exception filters in a predictable order.
- Keep direct access to the underlying platform through the public `Application` wrapper.
- Test applications with focused module builders, route snapshots, and provider overrides.

## Status

> [!IMPORTANT]
> Versions `1.0.0` and `1.0.1` were unintentionally released during CI/CD setup. Treat them as early alpha orphans. The first production-ready, non-alpha release target remains `2.0.0`.

- `bustan` is currently in the early `1.1.x` alpha series.
- The supported Python floor is currently `>=3.13`.
- Compatibility promises apply only to `bustan`, `bustan.errors`, and `bustan.testing`.
- Internal modules such as `bustan.core.*`, `bustan.app.*`, and `bustan.platform.*` are still implementation details.
- The public PascalCase API is already being treated as the intended long-term contract, even though alpha behavior may still move.

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
uv add bustan
uv add --dev pytest ruff ty
uv run bustan init
```

### Install The Published Package

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
uv add bustan
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

For the full walkthrough, generated file contents, and first test, see [docs/FIRST_APP.md](docs/FIRST_APP.md).

## What You Get Today

The current implementation already includes:

- module discovery, validation, and export-based provider visibility
- constructor injection for providers and controllers
- controller route compilation into Starlette
- inferred and explicit request binding with `Annotated[...]` markers
- response coercion for Starlette responses, `HttpResponse`, dataclasses, iterators, `Path`, and `None`
- request-scoped providers plus request-scoped controllers
- guards, pipes, interceptors, and exception filters
- automatic Pydantic validation in `validation_mode="auto"`
- module and provider lifecycle hooks wired through the platform lifespan
- `Application` and `ApplicationContext` bootstrapping
- route snapshots, route diffs, and runtime discovery support
- config, OpenAPI, throttling, CORS, and testing helpers
- a CLI (`bustan init`) for scaffolding new applications inside `uv` projects

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
from bustan.testing import create_test_app, override_provider
```

The generated reference for those stable modules lives in [docs/API_REFERENCE.md](docs/API_REFERENCE.md).

## Guides

- [docs/README.md](docs/README.md)
- [docs/FIRST_APP.md](docs/FIRST_APP.md)
- [docs/ROUTING.md](docs/ROUTING.md)
- [docs/REQUEST_PIPELINE.md](docs/REQUEST_PIPELINE.md)
- [docs/REQUEST_SCOPED_PROVIDERS.md](docs/REQUEST_SCOPED_PROVIDERS.md)
- [docs/LIFECYCLE.md](docs/LIFECYCLE.md)
- [docs/PLATFORM_INTEGRATION.md](docs/PLATFORM_INTEGRATION.md)
- [docs/STABILITY.md](docs/STABILITY.md)
- [docs/VERSIONING.md](docs/VERSIONING.md)
- [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)
- [docs/COMPARISONS.md](docs/COMPARISONS.md)

## Open Source Project Docs

- [CONTRIBUTING.md](CONTRIBUTING.md)
- [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
- [SECURITY.md](SECURITY.md)
- [GOVERNANCE.md](GOVERNANCE.md)
- [CHANGELOG.md](CHANGELOG.md)
- [docs/RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md)

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
from bustan.testing import create_test_app


application = create_test_app(
    AppModule,
    provider_overrides={GreetingService: FakeGreetingService()},
)
```

Use `override_provider()` when you want a scoped override that is restored automatically:

```python
from bustan.testing import override_provider


with override_provider(application, GreetingService, FakeGreetingService()):
    ...
```

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
uv run python scripts/generate_api_reference.py --check
uv run python scripts/check_markdown_links.py
uv run ruff check .
uv run ty check src tests scripts
uv run pytest
uv run pytest --cov=bustan --cov-report=term-missing --cov-report=xml
```

If you change public docstrings in the stable modules, regenerate the API reference with:

```bash
uv run python scripts/generate_api_reference.py
```

## Project Direction

Bustan is opinionated about application structure, not about hiding the underlying platform or competing on benchmark claims.

If you want a small ASGI core with explicit module boundaries, DI-managed services, lifecycle hooks, and a predictable request pipeline, that is the target use case for Bustan.

