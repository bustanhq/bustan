# Versioning Policy

`bustan` is currently in alpha (`v1.1.x`). Versions `1.0.0` and `1.0.1` were early accidental releases. The first production-ready release is still targeted at `2.0.0`.

## Public Compatibility Boundary

Compatibility commitments apply to:

- `bustan`
- `bustan.errors`
- `bustan.testing`

Everything else is internal and may change between alpha releases without a deprecation period.

## What Counts As A Public Change

The following should be treated as public-surface changes when they affect one of the stable modules:

- adding or removing an exported symbol
- changing callable signatures or class method contracts
- changing documented behavior visible through the stable modules
- changing structured error payloads exposed through the public runtime

The generated [API_REFERENCE.md](API_REFERENCE.md) is part of that public documentation trail because it is rendered from the docstrings attached to stable exports.

## Release Notes And Changelog

- Release notes are generated through the release-please workflow from Conventional Commits.
- Public-surface additions, removals, and behavior changes should be called out explicitly.
- Internal refactors may be summarized at a higher level when they do not change the supported public modules.

## Breaking Changes Before `2.0`

- Public API breaks may still happen before `2.0`, but they should be deliberate and documented.
- Compatibility breaks in the supported public surface should use clear release-note language and, when appropriate, `BREAKING CHANGE:` commit metadata.
- Internal modules do not carry the same notice requirement because they are not part of the compatibility target.

## Patch And Minor Expectations

- Patch releases should focus on fixes, documentation, packaging, and release-process hardening.
- Minor releases may expand the supported public surface or tighten behavior where the public contract is still settling.
- Python support should widen only after the current release automation and compatibility story are routine on the existing floor.