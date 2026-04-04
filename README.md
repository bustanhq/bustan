# star

star is an architecture-first Python web framework for teams that like Starlette's runtime but want stronger application structure.

It brings NestJS-style modules, controllers, providers, constructor injection, lifecycle hooks, and a request pipeline to Python, while keeping direct access to Starlette when you need an escape hatch.

## Why star

- Use modules as real composition boundaries instead of ad hoc import graphs.
- Keep controllers thin and move business logic into DI-managed providers.
- Apply guards, pipes, interceptors, and exception filters in a predictable order.
- Build on top of Starlette instead of replacing the ASGI layer with a closed runtime.
- Test applications with focused module builders and provider overrides.

## Status

- `star` is alpha and still pre-`0.1.0`.
- The first public compatibility target is `0.1.0` alpha.
- Package metadata currently targets Python `>=3.13`.
- The Python floor is intentionally narrow while the public surface, packaging, and release process are still settling.
- Python `3.13` remains the floor because the project is still tightening its first public contract and release automation around one supported runtime before widening support.
- Compatibility is currently promised only for `star`, `star.errors`, and `star.testing`.
- Internal modules such as `star.container`, `star.routing`, `star.params`, and `star.metadata` are still implementation details.
- Alpha stability means behavior may still change between pre-`0.1.0` releases, but the project is already treating `star`, `star.errors`, and `star.testing` as the intended long-term public surface.
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
uv run star new my-app
```

`create` is available as an alias:

```bash
uv run star create my-app
```

### Use as a published package

Once the PyPI distribution name is confirmed and published, the intended install path is:

```bash
uv add star
# or
pip install star
```

Once published, the CLI entry point will also be usable through `uvx`:

```bash
uvx star new my-app
```

The distribution name `star` still needs to be confirmed at publish time. The current repository is prepared for that name, but the final PyPI availability check should happen immediately before the first release.

## Five-Minute Quickstart

Create an application module, one provider, and one controller:

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

Run it locally:

```bash
uv run uvicorn app:app --reload
```

Call the route:

```bash
curl http://127.0.0.1:8000/hello
```

Expected response:

```json
{"message":"hello from star"}
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
- an initial CLI scaffold for new applications

## Supported Public API

The first compatibility boundary is intentionally small.

Stable import paths:

- `star`
- `star.errors`
- `star.testing`

Example supported imports:

```python
from star import __version__, controller, create_app, get, injectable, module
from star.errors import ProviderResolutionError
from star.testing import create_test_app, override_provider
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
- [docs/ESCAPE_HATCHES.md](docs/ESCAPE_HATCHES.md)
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
- `examples/testing_overrides/app.py`: test-time provider overrides with `star.testing`

Run them with:

```bash
uv run python examples/blog_api/app.py
uv run python examples/graph_inspection/app.py
uv run python examples/request_scope_pipeline_app/app.py
uv run python examples/testing_overrides/app.py
```

## Testing Utilities

`star.testing` is the intended entry point for test-time application assembly.

Use `create_test_app()` to start an app with one or more providers replaced:

```python
from star.testing import create_test_app


application = create_test_app(
	AppModule,
	provider_overrides={GreetingService: FakeGreetingService()},
)
```

Use `override_provider()` when you want a scoped override that is restored automatically:

```python
from star.testing import override_provider


with override_provider(application, GreetingService, FakeGreetingService()):
	...
```

Use `create_test_module()` when you want a temporary module class for an isolated test instead of declaring one manually.

## Support

Use GitHub Issues for questions, bug reports, feature requests, and adoption feedback:

- https://github.com/mosesgameli/star/issues

Do not use public issues for sensitive security reports. Follow the private disclosure guidance in [SECURITY.md](SECURITY.md).

## Roadmap

Near-term priorities for the first public adoption push:

- publish and verify the first PyPI release end to end
- widen runtime support beyond Python `3.13` once release automation is routine
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
uv run pytest --cov=star --cov-report=term-missing --cov-report=xml
```

## Project Direction

`star` is trying to be opinionated about application structure, not to hide Starlette or compete on benchmark claims.

If you want a small ASGI core with explicit module boundaries, DI-managed services, and a predictable request pipeline, that is the target use case.

