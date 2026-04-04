# Release Checklist

Use this checklist for every tagged release until the release workflow is fully routine.

## Before Release

1. Confirm the target version and release scope.
2. Verify the package name is still publishable on PyPI.
3. Ensure the changelog and release notes source is correct.
4. Confirm README, guides, and examples reflect the shipped behavior.

## Validation

1. Run `uv run python scripts/generate_api_reference.py --check`.
2. Run `uv run python scripts/check_markdown_links.py`.
3. Run `uv run ruff check .`.
4. Run `uv run ty check src tests examples scripts`.
5. Run `uv run pytest`.
6. Run `uv run pytest --cov=star --cov-report=term-missing --cov-report=xml`.
7. Run `uv build`.
8. Run `uvx --from twine twine check dist/*`.

## Publish Preparation

1. Confirm the version to publish.
2. Confirm release notes are generated from Conventional Commits.
3. Confirm CI is green on the supported platform matrix.
4. Confirm security and support links are still correct.
5. Confirm the public compatibility notes still match [VERSIONING.md](VERSIONING.md).
6. Confirm the current tag-signing policy in [GOVERNANCE.md](../GOVERNANCE.md).

## Publish

1. Create or merge the release PR.
2. Create the release tag.
3. Publish through the trusted publishing workflow.

## Post Publish

1. Watch [published-package-verification.yml](../.github/workflows/published-package-verification.yml) succeed for the released version, or run it manually with the new version number.
2. If manual verification is needed, install the package in a clean environment.
3. Verify `import star` succeeds.
4. Verify `star --help` succeeds.
5. Verify `uvx --from "star==<version>" star new my-app` scaffolds an application from the published artifact.
6. Publish or verify the GitHub release notes.
7. Announce the release if it is externally relevant.