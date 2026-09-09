# Documentation

These guides sit on top of the [project README](../README.md), which covers the pitch, installation
and the supported public surface.

**Requirements.** Python 3.13 or newer, and [uv](https://docs.astral.sh/uv/) as the package
manager. uv is the only one supported: the project is built, locked, tested and released with it.

**Upgrading from 1.x?** Start at [Migrate from 1.x](how-to/migrate-from-1x.md). 2.0 is a clean break
and a 1.x application will not start on it until it is corrected.

## How this is organised

Four kinds of document, after [Diataxis](https://diataxis.fr). The split is by what you are doing,
not by subject, so the same topic appears in more than one place on purpose.

| | For | Answers |
| --- | --- | --- |
| **[Tutorials](#tutorials)** | Learning | "Take me through it once." |
| **[How-to guides](#how-to-guides)** | A task in hand | "How do I do this?" |
| **[Reference](#reference)** | Looking something up | "What exactly does this do?" |
| **[Explanation](#explanation)** | Understanding | "Why is it like this?" |

Adding a document? Put it in the directory matching what a reader will be doing when they open it.
A guide that answers two of those questions is two documents.

## Tutorials

Learning-oriented. One path, start to finish, no choices to make.

- [Your first app](tutorials/first-app.md) - scaffold a runnable application, understand the
  generated files, run it, and add a first test.

## How-to guides

Task-oriented. You know what you want; these say how.

- [Migrate from 1.x](how-to/migrate-from-1x.md) - what `bustan doctor` finds, what only you can
  find, and a worked migration against a real 1.x application.
- [Choose a pipeline hook](how-to/choose-a-pipeline-hook.md) - which of guard, pipe, interceptor or
  filter a piece of work belongs in, with one request walked through every stage.
- [Deploy an application](how-to/deploy.md) - installing, serving, choosing an adapter, probes,
  draining and workers.
- [Observe an application](how-to/observe-an-application.md) - structured logging, correlation and
  trace context, the metrics and tracing protocols, and the two health probes.
- [Harden an application](how-to/harden-security.md) - request limits, throttling, authentication
  policy, CORS, and what never reaches a log.
- [Configure the underlying platform](how-to/configure-the-platform.md) - reaching the real platform
  object behind the adapter, and running with no HTTP at all.
- [Test an application](how-to/test-an-application.md) - starting an application with providers
  replaced, and building a throwaway module for one test.
- [Run the benchmarks](how-to/run-benchmarks.md) - what is measured, comparing a change on your own
  machine, and reading a failure.
- [Cut a release](how-to/cut-a-release.md) - validation, publishing prerequisites and post-publish
  checks. Maintainers only.

## Reference

Information-oriented. Look something up and leave.

- [API reference](reference/api.md) - every symbol in `bustan`, `bustan.errors` and
  `bustan.testing`. Generated from docstrings; do not edit by hand.
- [CLI](reference/cli.md) - `init`, `doctor`, `graph`, `config`, `routes`, `governance`, output
  formats and exit codes.
- [Errors](reference/errors.md) - one entry per exception the framework raises, keyed to the name in
  your traceback.
- [Routing](reference/routing.md) - controller prefixes, parameter binding, validation modes and
  response coercion.
- [Request pipeline](reference/request-pipeline.md) - execution order, `ExecutionContext`, automatic
  validation, global components and request limits.
- [Lifecycle](reference/lifecycle.md) - the hooks, who receives them, and their ordering across
  modules and providers.
- [Adapters](reference/adapters.md) - the port, the two shipped adapters, and the `Application`
  wrapper.
- [Stability](reference/stability.md) - what is public, what is internal, and how a new public API
  gets promoted.
- [Versioning](reference/versioning.md) - the compatibility contract and what counts as a public
  change.

## Explanation

Understanding-oriented. Background and reasoning, read away from the keyboard.

- [Request scope](explanation/request-scope.md) - what request scope gives you, when providers are
  built, and why some shapes are refused.
- [Layering](explanation/layering.md) - the package layering rule, why direction matters, and the
  gate that now enforces it.
- [The security model](explanation/security-model.md) - what a refusal deliberately withholds, and
  where the framework's responsibility stops.
- [Why the benchmark gate uses a ratio](explanation/why-the-benchmark-ratio.md) - why a ratio rather
  than a wall-clock number, and why the threshold is twenty percent.
- [Comparisons](explanation/comparisons.md) - how Bustan sits beside Starlette, FastAPI and
  NestJS-style architecture.

## Examples

Each example is a standalone project you can run.

- [Example index](../examples/README.md) - what each one demonstrates and how to run it.
- [blog_api](../examples/blog_api/README.md) - feature modules with a request-scoped actor.
- [multi_module_app](../examples/multi_module_app/README.md) - provider exports across modules.
- [graph_inspection](../examples/graph_inspection/README.md) - route snapshots and discovery.
- [request_scope_pipeline_app](../examples/request_scope_pipeline_app/README.md) - request-local
  state shared across guard, interceptor and controller.
- [testing_overrides](../examples/testing_overrides/README.md) - `create_test_app()` and
  `override_provider()`.
- [dynamic_module_usage](../examples/dynamic_module_usage/README.md) - a configurable dynamic module.

## Project

- [Changelog](../CHANGELOG.md) - every change, release by release.
- [Contributing](../CONTRIBUTING.md) - development setup and the checks to run.
- [Governance](../GOVERNANCE.md) - maintainer roles, release ownership and pause policy.
- [Security policy](../SECURITY.md) - how to report a vulnerability, and what is supported.

## Programme records

Kept for provenance rather than for reading. Neither is a guide.

- [Dependency-injection audit](audits/di-container-2026-09/REPORT.md) - the adversarial audit behind
  the 2.0 programme, with executable repros.
- [2.0 delivery backlog](delivery/BUSTAN_2_0_BACKLOG.md) - the ticket-by-ticket specification the
  release was built from.
