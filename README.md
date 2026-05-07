# Bustan

Bustan is a modular architecture engine for building scalable, testable ASGI applications. Inspired by NestJS, it provides a structured alternative to assembling micro-frameworks by hand.

It brings modules, controllers, providers, constructor injection, lifecycle hooks, and a request pipeline to the Python ecosystem, while maintaining direct access to the underlying platform (Starlette by default).

## Why bustan

- Use modules as real composition boundaries instead of ad hoc import graphs.
- Keep controllers thin and move business logic into DI-managed providers.
- Apply guards, pipes, interceptors, and exception filters in a predictable order.
- Decoupled from HTTP engines via the **Adapter** pattern (supporting Starlette, with Litestar planned).
- Test applications with focused module builders and provider overrides.

## Status

> [!IMPORTANT]
> Versions `1.0.0` and `1.0.1` were unintentionally released to PyPI and GitHub during CI/CD pipeline setup. These should be treated as early alpha orphans. The first real production-ready, non-alpha release will be `2.0.0`.

- `bustan` is currently in an early alpha stage (v1.0.1).
- The first intended production-ready target is `2.0.0`.
- Package metadata currently targets Python `>=3.13`.
- The Python floor is intentionally narrow while the public surface, packaging, and release automation are still settling.
- Compatibility is currently promised only for the public surface of `bustan`, `bustan.errors`, and `bustan.testing`.
- Internal modules such as `bustan.core.ioc`, `bustan.platform.http.routing`, and `bustan.metadata` are still implementation details.
- Alpha stability means behavior may still change, but the project is already treating the PascalCase public API as the intended long-term contract.
- No benchmark suite or benchmark claims are published yet.

## Installation

### Use from source today

This repository is ready to use directly in a local development environment:

```bash
uv sync --group dev
```

That installs the framework, test dependencies, linting, typing, and the local CLI entry point.

### Use the CLI from a source checkout

```bash
uv init --package my-app
cd my-app
uv add bustan
uv add --dev ty ruff
uv run bustan init
```

### Use as a published package

Once the PyPI distribution name is confirmed and published, the intended install path is:

```bash
uv add bustan
# or
pip install bustan
```

The distribution name `bustan` still needs to be confirmed at publish time. The current repository is prepared for that name, but the final PyPI availability check should happen immediately before the first release.

## Five-Minute Quickstart

Create an application module, one provider, and one controller:

```python
from bustan import Controller, Get, Injectable, Module, create_app


@Injectable
class GreetingService:
	def greet(self) -> dict[str, str]:
		return {"message": "hello from bustan"}


@Controller("/hello")
class GreetingController:
	def __init__(self, greeting_service: GreetingService) -> None:
		self.greeting_service = greeting_service

	@Get("/")
	def read_greeting(self) -> dict[str, str]:
		return self.greeting_service.greet()


@Module(
	controllers=[GreetingController],
	providers=[GreetingService],
	exports=[GreetingService],
)
class AppModule:
	pass


app = create_app(AppModule)
```

Run it locally:

```bash
uv run dev
```

Call the route:

```bash
curl http://127.0.0.1:3000/hello
```

Expected response:

```json
{"message":"hello from bustan"}
```

## What You Get Today

The current implementation already includes:

- module discovery and validation
- export-based provider visibility across modules
- constructor injection for providers and controllers
- controller route compilation into Starlette
- response coercion for `Response`, `dict`, `list`, dataclass instances, and `None`
- request binding for `Request`, path params, query params, and JSON body input
- request-scoped providers with per-request caching
- guards, pipes, interceptors, and exception filters
- module and application lifecycle hooks wired through Starlette lifespan
- test helpers for temporary modules, test apps, and provider overrides
- a CLI (`bustan init`) for scaffolding new applications into existing `uv` projects

## Supported Public API

The first compatibility boundary is intentionally small.

Stable import paths:

- `bustan`
- `bustan.errors`
- `bustan.testing`

Example supported imports:

```python
from bustan import __version__, Controller, Get, Injectable, Module, create_app
from bustan.errors import ProviderResolutionError
from bustan.testing import create_test_app, override_provider
```

The generated API reference for the stable surface lives in [docs/API_REFERENCE.md](docs/API_REFERENCE.md).

## Guides

- [docs/README.md](docs/README.md)
- [docs/FIRST_APP.md](docs/FIRST_APP.md)
- [docs/ROUTING.md](docs/ROUTING.md)
- [docs/REQUEST_PIPELINE.md](docs/REQUEST_PIPELINE.md)
- [docs/REQUEST_SCOPED_PROVIDERS.md](docs/REQUEST_SCOPED_PROVIDERS.md)
- [docs/LIFECYCLE.md](docs/LIFECYCLE.md)
- [docs/STABILITY.md](docs/STABILITY.md)
- [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)
- [docs/COMPARISONS.md](docs/COMPARISONS.md)
- [docs/PLATFORM_INTEGRATION.md](docs/PLATFORM_INTEGRATION.md)
- [docs/VERSIONING.md](docs/VERSIONING.md)

## Open Source Project Docs

- [docs/README.md](docs/README.md)
- [CONTRIBUTING.md](CONTRIBUTING.md)
- [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
- [SECURITY.md](SECURITY.md)
- [GOVERNANCE.md](GOVERNANCE.md)
- [CHANGELOG.md](CHANGELOG.md)
- [docs/RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md)

## Examples

The repository includes focused examples beyond the minimal quickstart:

- `examples/blog_api/app.py`: a small reference-style blog API with request context and module exports
- `examples/multi_module_app/app.py`: feature modules with exported providers
- `examples/graph_inspection/app.py`: print the discovered module graph
- `examples/request_scope_pipeline_app/app.py`: request-scoped providers shared across guards, interceptors, and controllers
- `examples/testing_overrides/app.py`: test-time provider overrides with `bustan.testing`

Run them with:

```bash
uv run python examples/blog_api/app.py
uv run python examples/graph_inspection/app.py
uv run python examples/request_scope_pipeline_app/app.py
uv run python examples/testing_overrides/app.py
```

## Testing Utilities

`bustan.testing` is the intended entry point for test-time application assembly.

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
- widen runtime support beyond Python `3.13`
- collect external adopter feedback before calling any release stable
- publish a fuller reference app or companion tutorial repository
- move to a dedicated docs site if the docs set outgrow README-driven discovery

## Development

Install hooks once after cloning if you want local pre-commit and pre-push checks:

```bash
uv run lefthook install
```

For full contributor expectations, see [CONTRIBUTING.md](CONTRIBUTING.md).

Run the main checks with:

```bash
uv run python scripts/generate_api_reference.py --check
uv run python scripts/check_markdown_links.py
uv run ruff check .
uv run ty check src tests examples scripts
uv run pytest
uv run pytest --cov=bustan --cov-report=term-missing --cov-report=xml
```

## Project Direction

`Bustan` is trying to be opinionated about application structure, not to hide the underlying platform or compete on benchmark claims.

If you want a small ASGI core with explicit module boundaries, DI-managed services, and a predictable request pipeline, that is the target use case for Bustan.

