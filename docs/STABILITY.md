# Stability Guide

`star` is still pre-`0.1.0`, but not every import path is equally stable.

## Supported Public Surface

These are the compatibility targets for the first public adoption push:

- `star`
- `star.errors`
- `star.testing`

Code samples, docs, and changelog guidance should treat those modules as the public contract.

## Internal Modules

Modules such as `star.container`, `star.metadata`, `star.params`, and `star.routing` are implementation details. They may change structure, signatures, or behavior between alpha releases without a deprecation window.

## Alpha Expectations

- Pre-`0.1.0` releases may still change behavior.
- Public-surface changes should still be called out in release notes and `CHANGELOG.md`.
- Internal refactors should not be described as public compatibility guarantees.

## Deprecation Expectations

- Public API removals or compatibility breaks should be called out explicitly in CI-generated release notes.
- New public APIs should land in `star`, `star.errors`, or `star.testing` only when they are intended for external use.
- Internal helpers should stay out of user-facing examples unless they are being promoted into the public surface.

For the release policy that backs this guide, see [VERSIONING.md](VERSIONING.md).