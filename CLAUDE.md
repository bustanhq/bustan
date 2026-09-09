# Working in this repository

Before writing an issue, a pull request description, a review or a comment, read
[WRITING.md](.agents/skills/bustan-supervisor/references/WRITING.md) and run
`.agents/skills/bustan-supervisor/scripts/check_writeup.py` on the draft
(`--file body.md --kind pr --title "..." --issue-body issue.md`; `--kind issue` or
`--kind comment` likewise). No attribution footers, session links or `Co-Authored-By`
and `Claude-Session` trailers, in a body, a comment or a commit. ASCII only in prose.

## Before writing code

Stop at the first rung that holds:

```
1. Does this need to exist?   -> no: skip it (YAGNI)
2. Already in this codebase?  -> reuse it, don't rewrite
3. Stdlib does it?            -> use it
4. Native platform feature?   -> use it
5. Installed dependency?      -> use it
6. One line?                  -> one line
7. Only then: the minimum that works
```

A pull request that adds a module, a dependency, a public symbol or an abstraction names
in its `## Decisions` section the rung it stopped at, and why the rungs above did not
hold.
