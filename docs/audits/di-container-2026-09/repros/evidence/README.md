# Evidence scripts

These are the verification scripts written and executed by the audit's
reproducer agents, one per finding, kept verbatim (plus a two-line header and
a file-level `ruff: noqa`). They are the primary evidence behind the
"Confirmed" status in [../../REPORT.md](../../REPORT.md); the decisive output
lines are quoted in each finding.

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

Run one with:

```bash
uv run python docs/audits/di-container-2026-09/repros/evidence/RI-01.py
```

File names carry the finding id used in the report; the header comment also
records the workflow's original `F-xx` id for cross-reference with the
audit transcript.
