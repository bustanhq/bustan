# Versioning Policy

This repository is still pre-`0.1.0`, but release behavior is not arbitrary.

## Public Compatibility Boundary

Compatibility commitments apply to:

- `star`
- `star.errors`
- `star.testing`

Everything else is internal and may change between alpha releases without a deprecation period.

## Release Notes And Changelog

- Release notes are generated in CI from Conventional Commits.
- Public-surface additions, removals, and behavior changes should be called out explicitly.
- Internal refactors may be summarized at a higher level when they do not change the supported public modules.

## Breaking Changes Before `1.0`

- Public API breaks may still happen before `1.0`, but they should be deliberate and documented.
- Compatibility breaks in the supported public surface should use clear release-note language and, when appropriate, `BREAKING CHANGE:` commit metadata.
- Internal modules do not carry the same notice requirement because they are not part of the compatibility target.

## Patch And Minor Expectations

- Patch releases should focus on fixes, documentation, packaging, and release-process hardening.
- Minor releases may expand the supported public surface or tighten behavior where the public contract is still settling.
- The project should widen Python support only after the current release process is routine on the existing floor.