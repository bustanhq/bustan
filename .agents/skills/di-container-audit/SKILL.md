---
name: di-container-audit
description: Adversarial audit checklist and executable repro harness for the bustan dependency-injection container (module graph, resolver, scopes, overrides, lifecycle, bustan.testing). Use when reviewing or changing code under src/bustan/kernel/ioc, src/bustan/kernel/module, src/bustan/kernel/lifecycle or src/bustan/testing, when triaging a ProviderResolutionError, a cross-request state leak, a scope bug or a container memory leak, or when asked to re-run, extend or verify the DI audit findings.
license: MIT
compatibility: Requires uv and Python 3.13 inside the bustan repository (run scripts with uv run python)
metadata:
  author: bustan maintainers
  version: "1.0"
  audit-report: docs/audits/di-container-2026-09/REPORT.md
---

# DI container audit

Use this skill to check the IoC container the way an attacker or a demanding
maintainer would: prove every claim with a script, keep the script, and report
file:line evidence.

## 1. Establish the baseline

```bash
cd <repo-root>
uv sync --group dev --frozen
uv run pytest -q
uv run ruff check .
uv run ty check src tests scripts
uv run ruff format --check src   # informational: formatting is not enforced by CI
```

## 2. Run the repro harness

Every known defect has a standalone script that prints one line per finding:

```
RESULT: <finding-id> REPRODUCED|FIXED|ERROR - <message>
```

```bash
uv run python .agents/skills/di-container-audit/scripts/run_repros.py
uv run python .agents/skills/di-container-audit/scripts/run_repros.py --verbose
uv run python .agents/skills/di-container-audit/scripts/run_repros.py --expect-fixed   # regression gate
```

- A finding that flips from REPRODUCED to FIXED means the fix landed: convert
  the script into a regression test under tests/ and delete the repro.
- ERROR means the script itself broke (an API rename, a missing dependency):
  fix the script before trusting the run.

The scripts live in docs/audits/di-container-2026-09/repros. Helper packages
that need real cross-module imports live in the _pkgs subdirectory there.

## 3. Audit new or changed code with the lenses

Read [references/LENSES.md](references/LENSES.md) and walk every lens that
touches the changed files. The lenses are ordered by the damage they find:
request isolation first, then concurrency and resource growth, then graph and
binding correctness, then reflection, overrides and lifecycle, then debt.

For each hypothesis:

1. Write a self-contained script (public API first: bustan, bustan.testing,
   starlette.testclient.TestClient; internal modules only when needed).
2. Run it. Never report a defect you did not execute unless it is a pure
   smell or documentation claim, and say so.
3. Try to refute it: is it documented as intended, unreachable from the
   public surface, or already covered by a test?

## 4. Write a new repro

Copy the shape of an existing script:

```python
"""<ID>: one-paragraph mechanism: what the code does and why it is wrong."""

from bustan import Injectable, Module, create_app_context


def main() -> None:
    ...  # build a tiny module graph, exercise the container
    if defect_observed:
        print("RESULT: <ID> REPRODUCED - <decisive observation>")
    else:
        print("RESULT: <ID> FIXED - <what was observed instead>")


if __name__ == "__main__":
    main()
```

Rules: ASCII only, ruff-clean (uv run ruff check docs/audits), no repository
edits, one RESULT line per sub-finding, deterministic output, under two
minutes.

## 5. Report

Severity guide used by the audit:

- critical: cross-request data leak or auth bypass reachable by an HTTP client
- high: wrong behavior of a documented feature, resource exhaustion, or silent misbinding
- medium: a footgun or drift that a normal user hits
- low: a smell with maintenance cost
- info: an observation

Each finding needs: id, title, severity, category, file:line locations, the
mechanism, a failure scenario, the repro script, and a proposed fix. Put the
findings in a report next to the repros and keep the maintenance roadmap in
the same document so priorities and evidence stay together. The current
report is docs/audits/di-container-2026-09/REPORT.md.
