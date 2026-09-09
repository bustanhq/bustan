# Documentation

These guides sit on top of the main [README.md](../README.md). Start there for the project overview, installation, supported public modules, and the CLI scaffold. Then use the guides below to go deeper into routing, the request pipeline, request scope, lifecycle hooks, platform access, operations, and release policy.

Upgrading from 1.x? Start at [how-to/migrate-from-1x.md](how-to/migrate-from-1x.md). 2.0 is a clean break and a 1.x application will not start on it until it is corrected.

## Recommended Reading Order

1. [tutorials/first-app.md](tutorials/first-app.md) for the generated project layout and the normal `bustan init` workflow.
2. [reference/routing.md](reference/routing.md) for controller prefixes, parameter binding, validation modes, and response coercion.
3. [reference/request-pipeline.md](reference/request-pipeline.md) for guards, pipes, interceptors, exception filters, and global pipeline tokens.
4. [explanation/request-scope.md](explanation/request-scope.md) for request-local state and scope constraints.
5. [reference/lifecycle.md](reference/lifecycle.md) for startup and shutdown ordering across modules and providers.

## Getting Started

- [tutorials/first-app.md](tutorials/first-app.md): scaffold a runnable app, inspect the generated files, run it locally, and add a first test.
- [reference/routing.md](reference/routing.md): controller structure, inferred versus explicit binding, `Annotated[...]` markers, and return-type behavior.
- [reference/request-pipeline.md](reference/request-pipeline.md): execution order, `ExecutionContext`, automatic validation, and custom pipeline components.
- [explanation/request-scope.md](explanation/request-scope.md): request-scoped providers, request-scoped controllers, and safe dependency direction.
- [reference/lifecycle.md](reference/lifecycle.md): `on_module_init`, `on_application_bootstrap`, shutdown hooks, and `create_app_context()`.
- [reference/cli.md](reference/cli.md): the `bustan` command line tool - `init`, `doctor`, `graph`, `config`, `routes`, and `governance`.

## Upgrading

- [how-to/migrate-from-1x.md](how-to/migrate-from-1x.md): what `bustan doctor` finds, what only you can find, and a worked migration validated against a real 1.x application.
- [../CHANGELOG.md](../CHANGELOG.md): every change, release by release, with the issue each one closed.

## Examples

The checked-in examples now mirror the standalone mini-project layout rather than the older one-file demos.

- [../examples/README.md](../examples/README.md): example index, run commands, and what each example demonstrates.
- [../examples/blog_api/README.md](../examples/blog_api/README.md): reference-style feature module plus request-scoped actor.
- [../examples/multi_module_app/README.md](../examples/multi_module_app/README.md): provider exports across feature modules.
- [../examples/graph_inspection/README.md](../examples/graph_inspection/README.md): route snapshots and runtime discovery.
- [../examples/request_scope_pipeline_app/README.md](../examples/request_scope_pipeline_app/README.md): request-local state shared across guard, interceptor, and controller.
- [../examples/testing_overrides/README.md](../examples/testing_overrides/README.md): `create_test_app()` and `override_provider()`.
- [../examples/dynamic_module_usage/README.md](../examples/dynamic_module_usage/README.md): a configurable dynamic module with injected tokens.

## Platform And Operations

- [reference/adapters.md](reference/adapters.md): `Application`, `ApplicationContext`, accessors for the underlying adapter, and runtime artifacts.
- [how-to/deploy.md](how-to/deploy.md): installing, serving, choosing an adapter, health probes, draining, workers, and gating a release.
- [how-to/observe-an-application.md](how-to/observe-an-application.md): structured logging, correlation and trace context, the metrics and tracing protocols, and the two health probes.
- [how-to/harden-security.md](how-to/harden-security.md): request limits, throttling, authentication policy, what a refusal is allowed to say, and what the framework does not do.
- [reference/errors.md](reference/errors.md): the common module graph, binding, scope, and lifecycle failures.
- [explanation/comparisons.md](explanation/comparisons.md): how Bustan fits beside Starlette, FastAPI, and NestJS-style architecture.

## Architecture And Performance

- [explanation/layering.md](explanation/layering.md): the package layering rule, why crossing it is a defect, why the check is advisory for now, and the violations still open.
- [how-to/run-benchmarks.md](how-to/run-benchmarks.md): what is measured, how run-to-run variation is divided out, and the CI gate that fails a regression.

## Audits

- [audits/di-container-2026-09/REPORT.md](audits/di-container-2026-09/REPORT.md): adversarial audit of the dependency-injection container (findings, executable repros, and the maintenance roadmap).
- [audits/di-container-2026-09/repros/evidence/README.md](audits/di-container-2026-09/repros/evidence/README.md): the captured output the audit's repro scripts are checked against.

## Stability And Release

- [reference/stability.md](reference/stability.md): what counts as public, what does not, and how to read the generated API reference safely.
- [reference/versioning.md](reference/versioning.md): alpha compatibility expectations and the current release contract.
- [reference/api.md](reference/api.md): generated reference for `bustan`, `bustan.errors`, and `bustan.testing`.
- [how-to/cut-a-release.md](how-to/cut-a-release.md): release validation, automation prerequisites, and post-publish smoke checks.
- [../GOVERNANCE.md](../GOVERNANCE.md): maintainer roles, release ownership, and pause policy.

## Delivery

- [delivery/BUSTAN_2_0_BACKLOG.md](delivery/BUSTAN_2_0_BACKLOG.md): the 2.0 programme's ticket-by-ticket specification, its orchestration rules, and the shared context every delivery agent works from.
