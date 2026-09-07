# Evidence scripts

These are the verification scripts written and executed by the audit's
reproducer agents, one per finding, kept verbatim (plus a two-line header).
They are the primary evidence behind the "Confirmed" status in
[../../REPORT.md](../../REPORT.md); the decisive output lines are quoted in
each finding.

They differ from the scripts one directory up:

- They print their own `CONFIRMED` / `REFUTED` lines instead of the
  `RESULT: <id> REPRODUCED|FIXED` protocol, so `run_repros.py` does not
  execute them.
- A few generate small helper packages next to themselves at run time
  (`_gen_*` directories); delete those after running.
- Some use internal modules (`bustan.kernel.*`, `bustan.app.bootstrap._create_app`)
  where the public surface has no equivalent, which is noted in the report.
- Six of them - `CR-05`, `QA-01`, `QA-02`, `QA-11`, `QA-12`, `QA-14` - still name the
  package tree as it stood when they ran, because each measures a module or test file
  that was later deleted rather than renamed. Their header comments say so. Every other
  script names the current tree.

## They are deliberately not linted

`ruff` does not lint or format this directory, and that is a decision rather
than an oversight. The scripts are the evidence behind a status in the report;
editing one to satisfy a checker changes what the reader is being shown. Two of
the findings cannot be satisfied at all:

- `PN-11` compares an enum token against a string with `is`, and that the two
  compare equal and hash equal while not being identical is the whole finding.
  The obvious repair deletes it.
- `CR-05` builds its service classes at run time and hands them in through a
  namespace dict, so a static checker cannot see them. There is no edit that
  satisfies the checker and preserves the scenario.

The suppression is a single entry in `tool.ruff.exclude` in the repository's
[`pyproject.toml`](../../../../../pyproject.toml). That is the only mechanism:
the scripts carry no file-level `noqa`, so there is one place to look and one
place to change. A handful of scripts do carry line-level `# noqa:` comments;
those were written by the reproducer agents and are part of the evidence.

The exclusion is honoured by `ruff check .` and `ruff format --check .`, which
is what CI and the pre-commit hook run. Passing a path in this directory to
`ruff` explicitly overrides the exclusion and will report several hundred
findings; that is expected, and none of them should be fixed.

GitHub code scanning is a separate tool and reads neither this file nor
`pyproject.toml`, so it still reports findings here and will comment on a pull
request that touches a line in this directory. Excluding the directory from it
is a repository settings change, not a change to any file in the tree. Until
that is made, such a comment describes the directory's nature and not the change
under review, and declining it is the correct response.

Run one with:

```bash
uv run python docs/audits/di-container-2026-09/repros/evidence/RI-01.py
```

File names carry the finding id used in the report; the header comment also
records the workflow's original `F-xx` id for cross-reference with the
audit transcript.
