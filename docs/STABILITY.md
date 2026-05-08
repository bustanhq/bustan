# Stability Guide

`bustan` is currently in alpha (`v1.1.x`). Versions `1.0.0` and `1.0.1` were released unintentionally during CI/CD setup and should be treated as early alpha orphans. The first production-ready release target remains `2.0.0`.

## Supported Public Surface

Compatibility commitments currently apply to three modules only:

- `bustan`
- `bustan.errors`
- `bustan.testing`

Code samples, docs, examples, and changelog guidance should treat those modules as the supported import surface.

## How To Read The API Reference

[API_REFERENCE.md](API_REFERENCE.md) is generated from the stable public modules above. When it says a symbol is "Defined in ...", that line identifies the implementation origin for browsing only. It is not a promise that the implementation module is itself public.

Import supported symbols from `bustan`, `bustan.errors`, or `bustan.testing`, not from the internal module shown as the implementation source.

## Internal Modules

Everything outside the three stable modules is internal for compatibility purposes. That includes namespaces such as:

- `bustan.app.*`
- `bustan.core.*`
- `bustan.platform.*`
- `bustan.pipeline.*`
- `bustan.config.*`
- `bustan.openapi.*`
- `bustan.security.*`

Those modules may change names, structure, signatures, or behavior between alpha releases without a deprecation window.

## CLI And Scaffold Expectations

The `bustan init` scaffold and the generated package layout are user-facing features, but they are still settling during alpha. Treat them as the current recommended workflow, not yet as a frozen long-term compatibility contract.

## Alpha Expectations

- Public-surface changes should still be called out in release notes and `CHANGELOG.md`.
- Internal refactors should not be described as public compatibility guarantees.
- New examples should stay on the stable import surface unless they are explicitly demonstrating an internal maintainer-only concept.

## Promoting A New Public API

If a symbol is meant to become public:

1. Export it from `bustan`, `bustan.errors`, or `bustan.testing`.
2. Add or update its docstring so the generated API reference is meaningful.
3. Regenerate [API_REFERENCE.md](API_REFERENCE.md).
4. Update the guides and examples to use the public import path.

For the release policy behind this guide, see [VERSIONING.md](VERSIONING.md).