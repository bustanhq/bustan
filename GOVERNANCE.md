# Governance

This document defines how `star` is currently reviewed, merged, released, and kept healthy while the project is still early.

## Maintainer Authority

- The current maintainer is Moses Gameli.
- The current maintainer may review, merge, and cut releases.
- If additional maintainers are added, this document should be updated in the same pull request that grants that responsibility.

## Review And Merge Expectations

- User-facing behavior changes should include tests and docs updates.
- Public API changes should stay within `star`, `star.errors`, or `star.testing` unless the compatibility boundary is intentionally being expanded.
- Larger changes should be reviewed before merge once the project has more than one active maintainer.

## Release Ownership

- Releases are currently cut by the maintainer through the release PR and trusted publishing workflow.
- The maintainer is responsible for confirming [docs/RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md) before tagging a release.
- Post-publish verification runs through [published-package-verification.yml](.github/workflows/published-package-verification.yml).

## Issue Triage And Release Cadence

- New issues should be triaged in GitHub Issues.
- Triage should happen at least weekly when the project is active.
- Releases are need-based, not date-based.
- Patch releases should happen for user-facing fixes, packaging regressions, or security-sensitive corrections.

## Contributor Paperwork

- This project does not require a CLA today.
- This project does not require DCO sign-off today.
- Contributions are accepted under the repository's MIT license.

## Tag And Release Signing

- Tags and releases are not signed before `0.1.0` alpha.
- This should be revisited once the release process is routine or if users ask for stronger supply-chain guarantees.

## Maintainer Absence Or Project Pause

- If the project becomes inactive or paused, the maintainer should communicate that state in a pinned GitHub issue and, if the pause is expected to last, in the README.
- If release ownership changes, update this file, the support guidance, and the release checklist together.