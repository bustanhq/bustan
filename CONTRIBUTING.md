# Contributing

Thanks for contributing to `bustan`.

The project is still pre-`0.1.0`, so the main goals right now are tightening the public API boundary, improving release safety, and making the framework easier to adopt without source-diving.

## Development Setup

Clone the repository, then install the development environment with `uv`:

```bash
uv sync --group dev
uv run lefthook install
```

## Quality Checks

Run the same checks locally that CI expects:

```bash
uv run python scripts/generate_api_reference.py --check
uv run python scripts/check_markdown_links.py
uv run ruff check .
uv run ty check src tests examples scripts
uv run pytest
uv run pytest --cov=bustan --cov-report=term-missing --cov-report=xml
```

If you change public docstrings in stable modules, regenerate the API reference with:

```bash
uv run python scripts/generate_api_reference.py
```

## Supported Python Version

The current public support floor is Python `3.13`.

Contributions should keep the repository green on the supported version and avoid introducing undocumented compatibility claims for older Python versions.

## Governance And Versioning

Project governance, review authority, release ownership, and pause policy live in [GOVERNANCE.md](GOVERNANCE.md).

Public-versus-internal compatibility rules live in [docs/VERSIONING.md](docs/VERSIONING.md).

This project does not require a CLA or DCO sign-off today. That choice may be revisited if the maintainer group or support obligations change.

## Project Conventions

- Prefer `uv` commands for local setup and execution.
- Keep changes focused. Avoid reformatting unrelated files.
- Preserve the supported public API boundary unless the change is explicitly about that contract.
- Treat `bustan`, `bustan.errors`, and `bustan.testing` as the compatibility surface. Internal modules are not yet stable.
- Add or update tests for behavior changes.
- Update docs when user-visible behavior, policy, or examples change.
- Do not introduce benchmark claims unless the repository also gains a benchmark harness and methodology.

## Commit Style

This repository is preparing for CI-generated changelogs based on Conventional Commits.

Use commit messages like:

- `feat: add request-scoped provider example`
- `fix: tighten provider resolution error message`
- `docs: clarify Python 3.13 support policy`

Use `!` or a `BREAKING CHANGE:` footer only for deliberate compatibility breaks.

## Pull Requests

Pull requests should:

- explain the problem being solved
- summarize the behavior or documentation change
- mention any follow-up work intentionally left out
- include tests for behavior changes
- include docs updates for user-facing changes

Before opening a PR, make sure the local quality checks pass.

## Security

Do not file public issues for sensitive security problems. Follow [SECURITY.md](SECURITY.md) instead.

## Code Of Conduct

By participating in this project, you agree to follow [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).