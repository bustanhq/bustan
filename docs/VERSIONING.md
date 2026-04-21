# Versioning Policy

`bustan` is currently in alpha (`v1.x`). Versions `1.0.0` and `1.0.1` were released unintentionally during CI/CD setup and should be treated as early alpha orphans. The first production-ready release will be `2.0.0`.

## Public Compatibility Boundary

Compatibility commitments apply to:

- `bustan`
- `bustan.errors`
- `bustan.testing`

Everything else is internal and may change between alpha releases without a deprecation period.

## Release Notes And Changelog

- Release notes are generated in CI from Conventional Commits.
- Public-surface additions, removals, and behavior changes should be called out explicitly.
- Internal refactors may be summarized at a higher level when they do not change the supported public modules.

## Breaking Changes Before `2.0`

- Public API breaks may still happen before `2.0`, but they should be deliberate and documented.
- Compatibility breaks in the supported public surface should use clear release-note language and, when appropriate, `BREAKING CHANGE:` commit metadata.
- Internal modules do not carry the same notice requirement because they are not part of the compatibility target.

## Patch And Minor Expectations

- Patch releases should focus on fixes, documentation, packaging, and release-process hardening.
- Minor releases may expand the supported public surface or tighten behavior where the public contract is still settling.
- The project should widen Python support only after the current release process is routine on the existing floor.