# Documentation

These guides sit on top of the main [README.md](../README.md). Start there for the project overview, installation, supported public modules, and the CLI scaffold. Then use the guides below to go deeper into routing, the request pipeline, request scope, lifecycle hooks, platform access, and release policy.

## Recommended Reading Order

1. [FIRST_APP.md](FIRST_APP.md) for the generated project layout and the normal `bustan init` workflow.
2. [ROUTING.md](ROUTING.md) for controller prefixes, parameter binding, validation modes, and response coercion.
3. [REQUEST_PIPELINE.md](REQUEST_PIPELINE.md) for guards, pipes, interceptors, exception filters, and global pipeline tokens.
4. [REQUEST_SCOPED_PROVIDERS.md](REQUEST_SCOPED_PROVIDERS.md) for request-local state and scope constraints.
5. [LIFECYCLE.md](LIFECYCLE.md) for startup and shutdown ordering across modules and providers.

## Getting Started

- [FIRST_APP.md](FIRST_APP.md): scaffold a runnable app, inspect the generated files, run it locally, and add a first test.
- [ROUTING.md](ROUTING.md): controller structure, inferred versus explicit binding, `Annotated[...]` markers, and return-type behavior.
- [REQUEST_PIPELINE.md](REQUEST_PIPELINE.md): execution order, `ExecutionContext`, automatic validation, and custom pipeline components.
- [REQUEST_SCOPED_PROVIDERS.md](REQUEST_SCOPED_PROVIDERS.md): request-scoped providers, request-scoped controllers, and safe dependency direction.
- [LIFECYCLE.md](LIFECYCLE.md): `on_module_init`, `on_application_bootstrap`, shutdown hooks, and `create_app_context()`.

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

- [PLATFORM_INTEGRATION.md](PLATFORM_INTEGRATION.md): `Application`, `ApplicationContext`, accessors for the underlying adapter, and runtime artifacts.
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md): the common module graph, binding, scope, and lifecycle failures.
- [COMPARISONS.md](COMPARISONS.md): how Bustan fits beside Starlette, FastAPI, and NestJS-style architecture.

## Stability And Release

- [STABILITY.md](STABILITY.md): what counts as public, what does not, and how to read the generated API reference safely.
- [VERSIONING.md](VERSIONING.md): alpha compatibility expectations and the current release contract.
- [API_REFERENCE.md](API_REFERENCE.md): generated reference for `bustan`, `bustan.errors`, and `bustan.testing`.
- [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md): release validation, automation prerequisites, and post-publish smoke checks.
- [../GOVERNANCE.md](../GOVERNANCE.md): maintainer roles, release ownership, and pause policy.