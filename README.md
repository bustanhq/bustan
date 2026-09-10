<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/bustanhq/bustan/v2.0.0/docs/assets/bustan-wordmark-dark.svg">
  <img src="https://raw.githubusercontent.com/bustanhq/bustan/v2.0.0/docs/assets/bustan-wordmark.svg" alt="Bustan" width="260">
</picture>

A modular architecture engine for building scalable, testable ASGI applications in Python.

[![CI](https://github.com/bustanhq/bustan/actions/workflows/ci.yml/badge.svg)](https://github.com/bustanhq/bustan/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/bustan.svg)](https://pypi.org/project/bustan/)
[![Python](https://img.shields.io/pypi/pyversions/bustan.svg)](https://pypi.org/project/bustan/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/bustanhq/bustan/blob/v2.0.0/LICENSE)

Bustan gives Python projects explicit composition boundaries, constructor injection, lifecycle
hooks and a predictable request pipeline, while still exposing the underlying platform directly.
The design follows NestJS; the semantics are Python's.

The HTTP transport sits behind an adapter port. Two adapters ship - Starlette, the default, and a
raw ASGI one needing no third-party web framework - and both are held to the same conformance
suite. An application that serves no HTTP needs neither.

## Why Bustan

- Modules as real composition boundaries, not ad hoc import graphs.
- Thin controllers, with business logic in dependency-injected providers.
- Guards, pipes, interceptors and exception filters in a documented order.
- Direct access to the underlying platform through the public `Application` wrapper.
- Applications you can test with focused module builders, route snapshots and provider overrides.

## Install

Requires **Python 3.13 or newer** and [uv](https://docs.astral.sh/uv/), which is the only supported
package manager.

```bash
uv add 'bustan[starlette]'
```

Plain `bustan` installs no web server. That is the install for using the framework as a library:
modules, providers and injection resolved through `create_app_context`, with no HTTP served.

Bustan is built, locked, tested and released with uv throughout. Another installer may resolve the
package, but nothing here is tested against one and no issue is accepted for one.

## Quickstart

```bash
uv init --package my-app
cd my-app
uv add 'bustan[starlette]'
uv add --dev pytest ruff ty
uv run bustan init
uv run dev
```

That scaffolds a runnable application, its tests, and `start` and `dev` script entries. Call it:

```bash
curl http://127.0.0.1:3000/
```

```json
{"message":"Hello from My App"}
```

The generated package:

```text
src/my_app/          __init__.py  app_module.py  app_controller.py  app_service.py
tests/my_app/        test_app_controller.py  test_app_module.py  test_app_service.py
```

For the walkthrough, the generated file contents and a first test, see
[Your first app](https://github.com/bustanhq/bustan/blob/v2.0.0/docs/tutorials/first-app.md) - the
first of [six tutorials](https://github.com/bustanhq/bustan/blob/v2.0.0/docs/README.md#tutorials)
that build a working link shortener from this scaffold.

## Documentation

[**Read the docs**](https://github.com/bustanhq/bustan/blob/v2.0.0/docs/README.md), organised by
what you are doing:

| | |
| --- | --- |
| [Tutorials](https://github.com/bustanhq/bustan/blob/v2.0.0/docs/README.md#tutorials) | Learning. One path, start to finish. |
| [How-to guides](https://github.com/bustanhq/bustan/blob/v2.0.0/docs/README.md#how-to-guides) | A task in hand: deploy, observe, harden, migrate, test. |
| [Reference](https://github.com/bustanhq/bustan/blob/v2.0.0/docs/README.md#reference) | Looking something up: API, CLI, errors, routing, lifecycle. |
| [Explanation](https://github.com/bustanhq/bustan/blob/v2.0.0/docs/README.md#explanation) | Understanding: request scope, layering, the security model. |

**Upgrading from 1.x?** 2.0 is a clean break and a 1.x application will not start on it until it is
corrected. Start at
[Migrate from 1.x](https://github.com/bustanhq/bustan/blob/v2.0.0/docs/how-to/migrate-from-1x.md);
`bustan doctor` finds most of it for you.

## What you get

**Composition and injection.** Module discovery, validation and export-based visibility.
Constructor injection for providers and controllers, with scope rules enforced while the
application is built rather than on the request that trips them. Singleton, request, durable and
transient lifetimes, plus request-scoped controllers. Dynamic modules and
`ConfigurableModuleBuilder`.

**Serving requests.** Route compilation onto either adapter behind one port. Inferred and explicit
binding with `Annotated[...]` markers. Response coercion for the neutral `HttpResponse`, the
transport's own responses, dataclasses, iterators, `Path` and `None`. Middleware, guards, pipes,
interceptors and exception filters. Automatic Pydantic validation. An `HttpException` family
covering fifteen statuses, rendered as RFC 9457 problem details - including the responses the
router itself produces. Finite request limits an application serves under whether or not it
configures them.

**Running in production.** Lifecycle hooks wired through the adapter's lifespan. Graceful shutdown:
readiness turns negative, in-flight requests drain, teardown hooks run with the signal's name, the
port is released. Liveness and readiness probes. Correlation ids, request timing, and pluggable
metrics and tracing sinks. Configuration, OpenAPI, throttling and CORS.

**Tooling.** `Application` and `ApplicationContext` bootstrapping, route snapshots and diffs,
runtime discovery, and a CLI: `init`, `doctor`, `graph`, `routes`, `config`, `governance`.

## Supported public API

The compatibility boundary is deliberately small: `bustan`, `bustan.errors`, `bustan.testing`.

```python
from bustan import Application, Controller, Get, Injectable, Module, create_app, create_app_context
from bustan.errors import ProviderResolutionError
from bustan.testing import create_test_app, create_testing_module
```

Everything else - `bustan.kernel.*`, `bustan.app.*`, `bustan.runtime.*`, `bustan.adapters.*` - is an
implementation detail and may be restructured without notice.
[Stability](https://github.com/bustanhq/bustan/blob/v2.0.0/docs/reference/stability.md) is the
authority on that boundary, and the export sets derive from it. The supported Python floor is
`>=3.13`.

## Examples

Each is a standalone project.
[Browse them](https://github.com/bustanhq/bustan/blob/v2.0.0/examples/README.md), or run one:

```bash
cd examples/blog_api
uv sync --group dev
uv run python -m blog_api.app
```

## Contributing

Issues and pull requests are welcome.
[CONTRIBUTING.md](https://github.com/bustanhq/bustan/blob/v2.0.0/CONTRIBUTING.md) covers development
setup and the checks to run;
[GOVERNANCE.md](https://github.com/bustanhq/bustan/blob/v2.0.0/GOVERNANCE.md) covers how decisions
get made.

```bash
uv sync --group dev
uv run lefthook install
uv run pytest
```

Report vulnerabilities privately, following
[SECURITY.md](https://github.com/bustanhq/bustan/blob/v2.0.0/SECURITY.md), not through public
issues. Participation is governed by the
[Code of Conduct](https://github.com/bustanhq/bustan/blob/v2.0.0/CODE_OF_CONDUCT.md).

## Project direction

Bustan is opinionated about application structure, not about hiding the underlying platform or
competing on benchmark claims. If you want a small ASGI core with explicit module boundaries,
injected services, lifecycle hooks and a predictable request pipeline, that is the target.

## License

[MIT](https://github.com/bustanhq/bustan/blob/v2.0.0/LICENSE)
