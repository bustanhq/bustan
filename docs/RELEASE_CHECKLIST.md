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
4. Run `uv run ty check src tests scripts`.
5. Run `uv run pytest`.
6. Run `uv run pytest --cov=bustan --cov-report=term-missing --cov-report=xml`.
7. Run `uv build`.
8. Run `uvx --from twine twine check dist/*`.

## When To Cut

A release is cut when a milestone empties, not when a number of commits have piled up.
The milestone is the release: "these issues are closed" is what the notes say, and the
issues carry the classification labels the notes are grouped by.

1. Confirm the milestone has no open issues.
2. Confirm the supervisor's own verification passes on the merged branch, not only that
   CI was green on each pull request: the suite, the audit repro harness with no verdict
   moved, the examples, the API reference check and the link check.
3. Confirm no release pull request or release bot is armed on `main`. One mechanism owns
   releases, and it is this one.

## Prepare The Release Commit

1. Compose the changelog entry from the milestone's closed issues, grouped by their
   classification labels. Every issue in the milestone appears, or the entry says why it
   does not.
2. Set the version in [pyproject.toml](../pyproject.toml). It is the only place a version
   is written down; nothing else in the repository repeats it.
3. Land both on `main` through a pull request, reviewed like any other change. This is the
   last point at which the release is reviewable, because a tag is not.

## Publish

1. Tag the merged commit as `v<version>`, matching [pyproject.toml](../pyproject.toml)
   exactly. [publish.yml](../.github/workflows/publish.yml) refuses a tag that names a
   different version than the commit packages.
2. Push the tag. The workflow re-runs the gates against that exact commit, builds, checks
   the distributions, publishes to PyPI, and then publishes the GitHub release with the
   changelog section for that version as its body.
3. A pre-release version - one carrying `a`, `b` or `rc` - is marked as a pre-release on
   GitHub automatically.

## Post Publish

1. Watch [published-package-verification.yml](../.github/workflows/published-package-verification.yml) succeed for the released version, or run it manually with the new version number.
2. If manual verification is needed, install the package in a clean environment.
3. Verify `import bustan` succeeds.
4. Verify `bustan --help` succeeds.
5. Verify that `uv init --package my-app`, `uv add "bustan==<version>"`, and `uv run bustan init` scaffold the expected package layout from the published artifact.
6. Confirm the scaffolded project contains `src/my_app/__init__.py`, `app_module.py`, `app_controller.py`, `app_service.py`, and the matching `tests/my_app/` files.
7. Publish or verify the GitHub release notes.
8. Announce the release if it is externally relevant.