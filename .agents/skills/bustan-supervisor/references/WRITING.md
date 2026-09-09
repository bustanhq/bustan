# Writing for the record

Everything the programme posts to GitHub - an issue, a pull request, a review, a comment
on the epic - is read later by a person who was not there: a maintainer tracing a
decision, a contributor reading the history behind a line. Write for that reader. The
agent on the other end needs the same facts, and reads a plain statement at least as
well as it reads a letter.

## The voice

A maintainer writing to a colleague who will read it in six months. Facts, decisions and
reasons. Third person for descriptions, imperative mood for instructions.

- State what is true and why. Do not narrate how it was found out, what was tried first,
  or what a tool refused to do.
- No first person in an issue body, a pull request body or an epic comment. A review
  states a decision as a decision - "Take the delete arm: nothing reads the policy files
  but the command's own defaults" - and a finding as a finding. It never says "I want to
  be", "I was wrong" or "you caught".
- Never address the reader as "you" in an issue body. "Grep the branch for the old name",
  not "Grep your own branch for". A path the ticket creates is marked `(new)`, not "yours
  to create".
- No apology, no reassurance, no compliment, no confession. A mistake is fixed by editing
  the text that carried it.
- No restating the rules. The channel rule, the blocked protocol and the ASCII rule live
  in the backlog once. A body that repeats them is longer and says nothing new.
- No attestation. "Every acceptance criterion is met" is the reviewer's finding to make.
  "Nothing arrived outside this pull request" is the channel rule restated as a
  confession.
- Sentence case, ASCII only, one idea per paragraph, no trailing period on a title.

## Titles

One clause, sentence case, at most 72 characters, saying what is wrong or what changes.
No ticket id, no finding id, no series prefix, no "this programme", no trailing period.

The id goes where search finds it and a title cannot lose it: the `ticket:T-NNN` label on
the issue, and a `Refs T-NNN` line at the top of the issue body and of the pull request
body. `label:ticket:T-500` finds the issue; `T-500 in:body` finds everything that cites
it.

A pull request title is the subject line of the change, so it keeps the Conventional
Commits prefix the commit-msg hook already demands, `type(scope): one clause`, with the
prefix counted inside the 72. One change per title: a comma-joined list is a pull request
that should be smaller, or a summary that belongs in the body.

Related tickets are grouped by the parent issue and the milestone, not by a prefix.
"Layering A:" says nothing a reader can act on; "Move the adapter port below the kernel"
does.

## Issue body

The issue stands alone for the work: a reader with the issue and the repository can do
the ticket. It does not stand alone for the programme's rules; the backlog does, and the
dispatch prompt sends every agent there.

```markdown
Refs T-500

## Context
Why the defect exists or why the change is wanted: the mechanism, present tense,
third person, one or two paragraphs. Quote the file and line where it helps.

## Change
What to do, imperative mood. Where the ticket leaves a choice open, name the
options and say which is preferred, or say the choice is the agent's to record.

## Acceptance
- One observable criterion per bullet, each reachable inside Owns, written as a
  checkable statement: the pull request ticks it as written.
- The finding ids this closes, as run_repros.py reports them.

## Owns
- `src/bustan/runtime/execution.py`
- `src/bustan/kernel/ioc/runtime/` (new)

## Must not touch
- `src/bustan/kernel/ioc/planning/`

## Delivery
Branch `feat/t-500-pipeline-memoization` from `main`.
```

A follow-up raised from a review has no ticket id; its first line cites what revealed it,
`Refs #274`, and names the acceptance criterion it undermines under `## Context`. Its
parent is the issue it came from, or the epic of the milestone it is deferred to when
that issue is closed, set with `gh issue edit N --parent P`. The `Refs` line does not
repeat the parent: GitHub shows the link on both issues and the check verifies it.

`## Delivery` is one line unless something differs from the backlog's defaults: a base
branch that is not `main`, or a verification command specific to this ticket.

`## Owns` is a bullet list of literal paths and nothing else, because the ownership gate
reads every backticked run between that heading and the next heading, bold lead-in or
rule. Prose about the list goes directly under it behind `**Notes on that list.**`, which
ends the section. Never wrap the section in `<details>`: the tags are not terminators,
the section runs on to the next heading, and whatever sits between is parsed as a path.

What the old bodies carried, and where it goes instead:

| Was in the body | Goes to |
| --- | --- |
| The working agreement: channel, blocked protocol, ASCII | The backlog's `## Orchestration model`. Nowhere on the issue. |
| The shared verification block | The backlog's `## Shared context brief`. The issue names only a command specific to the ticket, under `## Delivery`. |
| Narration of an amendment | The amendment itself, applied to the list, plus one line under `**Notes on that list.**`: date, path, the pull request that needed it. The edit history holds the diff. |
| Provenance ("reported by the T-600 agent in #274") | A `Refs` entry: `Refs T-600, #274`. |
| Sequencing and scheduler state | The epic's status table. An open issue means go, so the issue carries no schedule. |
| Which wave or series this belongs to | The parent link, `gh issue edit N --parent P`, never a title prefix or a sentence. |
| Second-person instructions | Imperative mood under `## Change`. |
| A generated-by footer | Nowhere. |

## Pull request body

```markdown
Closes #241
Refs T-502, DP-01, DP-02, DP-03, MG-08

## What changed
One or two paragraphs: the change and the reason, readable without the diff. Name
any public behaviour that changed.

## Acceptance
- [x] **The criterion, as written in the issue**: the test, file or command that
  proves it, one per box, in the issue's order.
- [ ] **A criterion not met, as written**: why, in a clause; it appears again under
  Not done.

## Verification
- `uv run ruff format --check . && uv run ruff check .`: All checks passed
- `uv run ty check src tests scripts`: All checks passed
- `uv run pytest --cov=bustan --cov-report=term-missing`: 1187 passed; TOTAL 96%
- `uv run python docs/audits/di-container-2026-09/run_repros.py`: 0 reproduced, 84 fixed; DP-01, DP-02, DP-03, MG-08 moved from REPRODUCED to FIXED
- `uv run python scripts/generate_api_reference.py --check`: up to date
- `uv run python scripts/check_markdown_links.py`: no link errors
- `uv run python scripts/run_examples.py`: all examples passed
- `uv run python scripts/check_layering.py`: no violations
- `uv run python scripts/conformance_matrix.py`: all rows conform

## Decisions
- Only where the ticket left more than one defensible option: the option taken and
  the reason, one or two sentences each.
- For any new module, dependency, public symbol or abstraction: the rung of the
  ladder in `CLAUDE.md` it stopped at, and why the rungs above did not hold.

## Not done
- Only omissions inside the ticket's scope, each with its reason, an unticked
  criterion among them quoted as written. Or the one line:
  Nothing in scope was left undone.
```

`## Acceptance` quotes each criterion as the issue states it, in bold, then the
evidence: a test id, a file, a command and its status line, or the row of a table
elsewhere in the body. The check compares the first 60 characters of each criterion,
so a paraphrase does not count; a box left unticked is a criterion not met, and the
same criterion goes under `## Not done` with its reason.

The figures are illustrative; a real body carries the numbers its own run printed. One
line per command: the command and its final status line, edited only to drop timing. A
measurement the ticket asked for is one line, before and after, under `## Verification`.
Full output, if a reviewer could need it, goes in one collapsed
`<details><summary>Full verification output</summary>` block after the list, and never a
pytest collection listing, an example application's stdout or a JSON dump.

`Closes #N` is plain text on its own line. Inside backticks it is a code span, and GitHub
does not read closing keywords from a code span. A change with no issue behind it, such
as repository maintenance, carries `Refs` alone and is checked with `--no-issue`; a
delivery pull request always closes its ticket.

Not in the body: a "Files touched" list (the diff tab is that list), a note on how the
work was directed, a checkbox outside `## Acceptance`, attestations, footers, session
links.

A `BLOCKED:` or `DECISION REQUIRED:` draft keeps that first line, then the problem in one
paragraph, the options as bullets, and the recommendation with its reason. It does not
narrate what was tried.

## Review comments

A review is a verdict and a list of findings. Nothing else.

- First line: the verdict, `APPROVE` or `REQUEST_CHANGES`. When the tooling forces a
  `COMMENT` submission, the first line still names the verdict it carries.
- Each finding inline on the line it concerns: what is wrong, what to change, why. Three
  sentences is the usual length; a `suggestion` block where the fix is a line.
- The summary lists the findings and answers anything the pull request asked, decision
  and reason, in the order asked.
- A decision the agent needs is stated once, as a decision. Not as a reflection on the
  recommendation, and not with an account of who was consulted.
- A reviewer's own earlier error is recorded as a fact and its correction: "The earlier
  grant listed five tests; one never referenced release-gate and stays." Not as a
  section about what the reviewer got wrong.
- A wrong comment is edited, with one line at its end saying what changed. A second
  comment correcting the first is two wrong records instead of one.
- Tool limitations never go on the pull request. Submit the way that works and say
  nothing about the way that did not.
- A grant of a file outside `Owns` is an edit to the issue's `## Owns` list, then one
  line on the pull request: "Owns amended: added `path` (issue #N)."

## Epic body and comments

The epic body is the wave's purpose in a paragraph, the sequencing table and the risks.
It is already that shape; keep it. An epic carries the `epic` label, is the one issue
with no parent, and owns no files; every ticket and follow-up hangs under one.

An epic comment is one of three things, named in its first line:

- **Status.** A table: ticket, issue, state, pull request. One line per row that needs
  one, no prose beyond it.
- **Validation.** The table VALIDATION.md asks for: one row per claim, what was observed,
  what was done about it. A dropped claim is a row, not a paragraph.
- **Decision.** The decision, the reason and what it changes, as bullets.

Command output is reduced to its status line, never pasted. No first person, no account
of what was checked by hand, no section titled with what the writer got wrong.

## Budgets

| Artifact | Limit |
| --- | --- |
| Issue or pull request title | 72 characters |
| Issue body, excluding the `Owns` and `Must not touch` lists | 400 words |
| Pull request body, excluding `## Acceptance`, `## Verification` and any `<details>` block | 300 words |
| `## Acceptance` checklist | one box per criterion, at most 12 |
| `## Verification` list | one line per command, at most 12 lines |
| Fenced output outside `<details>`, whole body | 20 lines |
| Pull request body including `<details>` | 10,000 characters |
| Review summary, or an answer to a draft | 150 words |
| Inline review comment, excluding a `suggestion` block | 60 words |
| Epic comment, excluding tables | 200 words |
| Any other comment: grant notice, status reply | 60 words |

Word counts leave out fenced blocks, tables, `<details>` blocks and HTML comments. These
are the defaults of `scripts/check_writeup.py`. A body that needs more is usually two
pull requests, or an issue that should be split.

## Banned content

The check refuses a title, body or comment containing any of these, case-insensitively:

- Footers and provenance: `Generated by [Claude Code]`, `claude.ai/code/`, `session_`
  followed by an id, `Co-Authored-By: Claude`, `Claude-Session:`.
- Self-address: `I want to be`, `I was wrong`, `I got wrong`, `Correcting my`,
  `Correcting the`, `I said I would`, `you caught`, `beat my grep`, `deserved better`.
- Attestation: `Nothing arrived outside`, `Every acceptance criterion is met`, `nothing
  outside Owns`, `both granted paths are used`.
- Programme chatter: `Supervisor amendment`, `as a finding rather than acted on`, `Read
  this section before anything else`, `yours to create`, `pasted verbatim`.
- Tool narration: `GraphQL is not served`, `only the pinned set`, `this session`, `I
  cannot undraft`.
- In a title: `this programme`, a ticket id (`T-` and three digits), a finding id (`CR`,
  `DP`, `EX`, `MG`, `OL`, `PN`, `QA`, `RF`, `RI` and two digits), a series prefix such as
  `Layering A:`.
- Headings: `Working agreement`, `Verification block`, `Files touched`, `Note on how
  this work was directed`, `Decisions where more than one option was defensible`, `What
  was deliberately not done`, `What I verified`, `Two things I got wrong`; and
  `**Sequencing.**` as a lead-in in a ticket, since an epic's sequencing table is the
  one place a schedule belongs.
- A checkbox anywhere but under `## Acceptance` in a pull request: the old template's
  Validation, Docs and Release Notes boxes, ticked or not.

## Attribution

No footer, no generated-by line, no session link, no `Co-Authored-By` or
`Claude-Session` trailer, in a body, a comment or a commit. The repository's
`.claude/settings.json` sets `attribution.commit` and `attribution.pr` to empty strings
and `attribution.sessionUrl` to false, which turns the defaults off in every session that
clones it. The check catches a footer or a link that arrives anyway, and
`git log --format=%(trailers) BASE..HEAD` on the branch catches a trailer.

## Three rewrites

**An issue title.** Before, 143 characters:

> A transport request annotation is matched by shape, so one adapter hands over the
> other adapter's request object - and never recognises its own

After, with the mechanism moved to `## Context`:

> Match transport request annotations by adapter, not by shape

**A verification section.** Before: a heading "Verification block, pasted verbatim"
followed by the full pytest collection listing, an example application's stdout and a
JSON module-graph dump, two thirds of a body that ran to many thousands of words for a
three-file change. After: the list shown under "Pull request body" above, and nothing
else.

**A review opening.** Before:

> The maintainer has chosen the ticket's second arm. Delete `bustan governance
> release-gate`, and the two policy files with it.
>
> I want to be straight with you about your recommendation, because it deserved better
> than a silent no. Keeping the command and deleting only the two JSON files was the
> sharpest thing in this pull request. ...

After, the first lines of the review:

> REQUEST_CHANGES.
>
> Decision: delete `bustan governance release-gate` and its two policy files.
> `release/config.json` and `release/manifest.json` are read by nothing but the command's
> own argument defaults, and the repository has no routes to gate. The pull request's
> recommendation, keep the command and delete only the files, was put to the maintainer
> as the preferred option; the maintainer chose the delete arm.
>
> Owns amended on the issue: `docs/CLI.md`, `docs/DEPLOYMENT.md`, `SECURITY.md`. Required:
> remove the release-gate usage line and bullet from `docs/CLI.md`, its row from the
> deployment guide's release-gating table and the release-gate cases from the CLI tests;
> replace the alpha claim in `SECURITY.md` with the reconciled version statement. Leave
> `governance ownership`, `diff` and `conformance` untouched.
