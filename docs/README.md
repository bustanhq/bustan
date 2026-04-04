# Documentation

These guides sit on top of the main [README.md](../README.md). Start there for the project overview, installation, and public API boundary, then use the docs below for deeper adoption work.

## Getting Started

- [FIRST_APP.md](FIRST_APP.md): build a small app with modules, providers, controllers, DI, and a first test.
- [ROUTING.md](ROUTING.md): route decorators, parameter binding, and response behavior.
- [REQUEST_PIPELINE.md](REQUEST_PIPELINE.md): guards, pipes, interceptors, filters, and execution order.
- [REQUEST_SCOPED_PROVIDERS.md](REQUEST_SCOPED_PROVIDERS.md): request-local state and request-aware dependencies.
- [LIFECYCLE.md](LIFECYCLE.md): startup and shutdown hooks, ordering, and failure behavior.

## Stability And Maintenance

- [STABILITY.md](STABILITY.md): what is public, what is internal, and how alpha compatibility is treated.
- [VERSIONING.md](VERSIONING.md): release compatibility rules for public modules versus internal implementation details.
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md): the most common framework errors and how to fix them.
- [COMPARISONS.md](COMPARISONS.md): how `star` differs from Starlette, FastAPI, and NestJS.
- [ESCAPE_HATCHES.md](ESCAPE_HATCHES.md): direct use of Starlette and low-level integration points.

## Reference And Release

- [API_REFERENCE.md](API_REFERENCE.md): generated API reference for the supported public surface.
- [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md): release validation, publish, and post-publish verification steps.
- [GOVERNANCE.md](../GOVERNANCE.md): maintainer roles, triage cadence, release ownership, and pause policy.