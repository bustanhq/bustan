# Bustan 2.0 delivery backlog

Seven days, eight releases, 91 audit findings closed, delivered by parallel AI agents
against independently mergeable tickets.

## How to use this document

This one file is the shared source of truth for every agent on the programme. Before
work starts the supervisor commits it to the repository at
`docs/delivery/BUSTAN_2_0_BACKLOG.md` so that every agent, in every session or
worktree, reads the same copy and every PR reviewer can cite it. Nothing outside the
repository is a dependency of the work.

**If you are a delivery agent**, you are dispatched with one ticket id. Read, in this
order: `## Context` (why any of this is happening), `## Orchestration model` (the
rules you must not break), `## Shared context brief` (repo facts and standards that
apply to every ticket), and then **only your own ticket**. Skip every other ticket.
Skip `## Wave map`, `## Coverage of the audit` and `## Risks`; those are supervisor
material. Your ticket is self-contained: it states why the defect exists, what to
change, which files you may touch, and how you will be judged. If it does not, say so
in a draft pull request before writing code rather than guessing.

**You work remotely and the pull request is your only channel.** There is no chat
with the supervisor, no shared terminal and no way to ask a question and wait for an
answer. Anything you need to say, you say in a PR: a draft PR to raise a problem
early, the PR description to record a decision, a PR comment to answer a review. You
cannot see the other agents, their branches or their work in progress, and you must
not try to infer it. Everything you need is either in this document, in your own
checkout, or is a question for a draft PR. This is also why your ticket's
dependencies are already merged before you are dispatched: the supervisor's dispatch
is itself the signal that the ground under you is stable.

**If you are the supervisor**, read the whole file, and `## The GitHub loop` most
carefully. You open one issue per ticket at the start of each wave, review every pull
request against its acceptance criteria, review `main` after every merge, raise
follow-up issues for drift, and cut releases.

**Dispatch prompt.** Each agent is started with exactly this, and nothing else:

> You are a delivery agent on the Bustan 2.0 programme. Your work order is issue
> **#N** in this repository: read it in full, it is self-contained. Then read
> `docs/delivery/BUSTAN_2_0_BACKLOG.md` and follow its "How to use this document"
> section for the rules that apply to every ticket. Do not modify any file outside the
> issue's `Owns` list. When you are done, open one pull request that follows the PR
> contract and includes `Closes #N`.

## Context

The adversarial audit in `docs/audits/di-container-2026-09/REPORT.md` found 91 defects
in the dependency-injection container, 84 demonstrated by executed scripts kept in
`docs/audits/di-container-2026-09/repros/`. One is critical: a default-scope
controller that injects a request-scoped provider serves the first caller's identity
to every later caller, which the documentation says raises an error and does not.

Three follow-up surveys found the same pattern outside the container. Starlette is
referenced 56 times across 23 files in 8 packages including the injection kernel, so
"server agnostic" is aspiration rather than fact and no second adapter has ever been
written to test it. `@Cache`, `@Idempotent`, `@Audit` and the per-route arguments of
`@RateLimit` compile into a plan that no runtime code reads. There is no request
duration metric, no correlation id, no health endpoint, no graceful shutdown
(`close()` is `pass`), no request timeout, no body-size limit and no `HttpException`,
so an application cannot return a 404 through the framework's own error model. The
coverage gate rounds 94.53 up to 95 and exits zero, `ruff` selects no lint rules, and
six tests assert defective behaviour as the contract.

The project's changelog states 1.0.0 and 1.0.1 were accidental and 2.0.0 is the first
production-ready release. This backlog makes that true.

**Decisions taken with the user:** ports plus a proof adapter with Starlette as an
optional extra; a focused operability set rather than a full resilience stack; a real
1.1.1 security patch then release candidates then 2.0.0; a clean break with a
migration guide and a `bustan doctor` scanner rather than compatibility shims.

## Orchestration model

**Roles.** One supervisor: turns each ticket in this backlog into a GitHub issue,
reviews every pull request against its acceptance criteria, runs the verification
independently rather than trusting the pasted output, answers `BLOCKED:` and
`DECISION REQUIRED:` drafts in review comments, reviews `main` after every merge and
raises follow-up issues for what the tickets did not anticipate, owns the merge queue
and cuts releases. N delivery agents, working remotely and independently: each is
given one issue, works on one branch, opens one pull request, and communicates only
through it.

**The team is remote and asynchronous.** Agents cannot see each other or the
supervisor. Every instruction an agent receives is either in this document or in a
review comment on its own pull request, and every message an agent sends is a pull
request or a comment on one. The design consequence runs through the whole backlog:
tickets are sized so that one agent can finish one without needing to talk to anyone,
dependencies are resolved by wave sequencing rather than negotiation, and the two
places where a genuine conversation is unavoidable (T-403's inherited signature and
T-407's product decision) are restructured so the conversation happens as a review
comment on a draft PR.

**Rules that make parallelism safe.**

1. A ticket lists `Owns` (files it may create or modify) and `Must not touch`. An
   agent that needs a file outside `Owns` stops and raises a draft PR rather than
   editing it. This is the single most important rule: it is what lets agents who
   cannot see each other work on the same repository at the same time.
2. Tickets in the same wave have disjoint `Owns` sets by construction, so they never
   conflict. Waves are barriers: a wave merges completely before the next starts.
3. Branch name is the ticket id in lower case, for example
   `feat/t-102-annotation-resolution`. One ticket, one branch, one PR.
4. Commits use Conventional Commits with the ticket id in the body. A `BREAKING
   CHANGE:` footer is mandatory whenever `bustan.__all__`, a public signature or a
   documented behaviour changes.
5. Every PR body follows the contract below. Because the PR is the only channel, a PR
   that omits part of it cannot be reviewed and will be returned unread.
6. Rebase onto the wave's integration branch before requesting review; never merge
   the integration branch into the ticket branch.
7. One agent per ticket, assigned by the supervisor. An agent never picks up a second
   ticket, and never starts a ticket it was not dispatched for, even when it looks
   blocked or trivial. Tickets are claimed by dispatch, not by initiative, so two
   agents cannot converge on the same work.

**The PR contract.** Every pull request description contains, in this order: the
ticket id and title; the audit finding ids closed; a short statement of what changed
and why, in prose a reviewer can read without opening the diff; the list of repro
scripts that moved from `REPRODUCED` to `FIXED`; the verification block output pasted
verbatim; every decision you made where the ticket left more than one defensible
option, each with the reason; and anything you deliberately did not do, with why.
That last item matters most: a silent omission is indistinguishable from an oversight
to a reviewer who cannot ask you.

**When you are blocked.** You never wait. You open a draft PR whose description
begins with `BLOCKED:` and a one-paragraph statement of the problem, containing
whatever work is already done, and then you stop. The partial work stays reviewable
and survives if the ticket is reassigned. Four situations warrant it:

- You need to change a file outside your `Owns` list. Name the file and say why. Do
  not edit it, and do not work around it by duplicating logic into a file you do own,
  which is worse than the original problem.
- Your ticket's context contradicts the code. Quote the file and line. The plan may be
  wrong, and the supervisor must know before later tickets inherit the error.
- Your ticket asks for a decision it does not settle, and the choice is not obviously
  reversible. Put your recommendation and the alternatives in the draft PR.
- A dependency you were told had merged is missing from your checkout. Do not proceed
  on an assumption about what it will contain.

For a design question that *is* cheaply reversible, do not block. Choose the option
that keeps the public surface smallest, implement it, and record the choice and your
reasoning in the PR description. A reviewer can redirect a merged decision far more
easily than an idle agent.

**Review gate.** The supervisor merges only when: acceptance criteria are each
demonstrably met, the full verification block passes locally, the named repro scripts
report `FIXED`, no file outside `Owns` is modified, and public docstrings on any
changed public symbol read as plain English an unfamiliar engineer can act on.

**Integration branches.** `release/1.1.1` cut from the `v1.1.0` tag for the security
patch. `main` carries the 2.0 line. Each wave merges to `main` behind a wave
integration branch (`integration/wave-N`) so the supervisor can run the full
verification once on the combined result before it reaches `main`.

## The GitHub loop

GitHub is the whole coordination surface. The backlog is the specification, an issue
is a work order, a pull request is the delivery and the conversation, and the merge
queue is the schedule. Nothing is agreed anywhere else.

### Waves are sequential, tickets are parallel

Read this before assigning anyone work, because it is the constraint people get wrong.
**Two agents cannot take two different waves at the same time.** Wave 2 is written
against the kernel wave 1 produces; wave 4 refers to paths that only exist after wave
3's move; wave 5 memoizes a pipeline whose override rule wave 2 defines. A wave is a
barrier, not a lane.

What *is* parallel is the tickets inside the current wave, and that is where the
throughput comes from: four agents in wave 1, four in wave 2, five in wave 3, seven in
wave 4. The supervisor opens the next wave's issues only when the current wave's are
all closed. An agent is therefore always dispatched into a repository whose ground is
stable, which is what lets the ticket be self-contained.

The one exception is wave S, the 1.1.1 security patch. It targets a branch cut from
the released tag and shares no files with the 2.0 line, so it runs beside wave 0 with
no interaction.

### Supervisor: create the issues

At the start of each wave, one issue per ticket, created with `issue_write`:

- **Title** `T-NNN <ticket title>`, so the id is greppable and sorts naturally.
- **Body** is the ticket copied verbatim from this backlog: context, scope, owns, must
  not touch, acceptance. The issue is what the agent reads, so it must stand alone;
  never write "see the backlog for details".
- **Labels** `wave-N`, `ticket:T-NNN`, and one of `security`, `correctness`,
  `architecture`, `operability`, `docs`.
- **Milestone** the release the wave ships: `1.1.1`, `2.0.0-rc.1` and so on. The
  milestone burndown then shows release readiness without a separate tracker.
- **Hierarchy** one epic issue per wave, with the ticket issues attached as sub-issues
  via `sub_issue_write`. The epic's sub-issue summary is the wave's progress bar, so
  the pinned ledger becomes unnecessary; GitHub keeps the state.

Dependencies inside a wave (T-104 after T-100 to T-103, T-404 after T-400, T-306 last)
are expressed by *withholding the issue* until its dependency closes, not by writing
"blocked by" and trusting an agent to wait. An open issue means go.

### Agent: work the issue, open the pull request

The agent is given a repository and an issue number and nothing else. It reads the
issue, reads `docs/delivery/BUSTAN_2_0_BACKLOG.md` for the shared rules, branches as
`feat/t-nnn-<slug>`, and opens one pull request whose description follows the PR
contract and contains `Closes #N` so the merge closes the issue automatically. Draft
PRs carry `BLOCKED:` or `DECISION REQUIRED:` as the first line of the description.

### Supervisor: review the pull request

In this order, because the cheap mechanical gates should fail before anyone reads
logic:

1. `pull_request_read` with `get_files`. Compare the changed paths against the
   ticket's `Owns` list. A file outside it is an immediate `REQUEST_CHANGES`
   regardless of how good the code is, because the guarantee that keeps parallel
   agents from corrupting each other is the ownership rule, and an exception granted
   once stops being a rule.
2. `get_check_runs`. CI must be green. A red PR is not reviewed.
3. Confirm the PR body carries every element of the contract. A missing "what I
   deliberately did not do" section is a returned PR; a reviewer who cannot ask
   questions depends on it.
4. `get_diff`, and read it against the acceptance criteria one at a time.
5. Run the verification block locally on the branch rather than trusting the pasted
   output. The paste proves the agent ran it; your run proves it passes.
6. `pull_request_review_write` with `create` to open a pending review,
   `add_comment_to_pending_review` for each inline finding, then submit as
   `APPROVE` or `REQUEST_CHANGES`. A review comment is the only way to answer a
   `BLOCKED:` or `DECISION REQUIRED:` draft, so make it complete enough to unblock in
   one round: state the decision and the reason, not just the verdict.

### Supervisor: review main, not just the diff

A PR can satisfy its own acceptance criteria and still leave the branch worse. After
each merge, and always before closing a wave, review `main` itself against this plan:

- Run the full verification block on `main`, including the repro harness. Findings the
  wave claimed to close must report `FIXED`, and findings it did not touch must not
  have regressed to `REPRODUCED`.
- Check the wave's collective intent, which no single ticket owns. After wave 1, is
  planning genuinely separated from execution, or did one ticket smuggle reflection
  back into the runtime path? After wave 3, does `check_layering.py` pass and does the
  package install without a web server? After wave 4, is there one error contract or
  two?
- Check for drift the tickets did not anticipate: a new `Any` on a public signature, a
  comment referencing something outside the repository, a duplicated helper that
  should have been shared, a docstring that no longer matches behaviour.

Anything found here becomes a **follow-up issue**, never a silent fix and never an
unrecorded complaint: `issue_write` with label `follow-up`, a body naming the PR that
introduced it and the acceptance criterion it undermines, attached to the wave epic if
it blocks the release or to a later wave if it does not. Follow-ups that block a
release are closed before its milestone closes; the rest ride to 2.0.0 or are
deliberately deferred with that decision written down.

### Where the audit fits

`run_repros.py` is the objective referee for the whole programme, and it lives in the
repository, so both the agent and the supervisor run the same check. When a ticket
claims a finding, its repro flipping to `FIXED` is the evidence; when the supervisor
reviews `main`, the same harness catches anything a merge broke. From T-503 it is a
blocking CI job, at which point the review gate for regressions becomes automatic and
the supervisor's judgement is spent on design rather than on detection.

## Shared context brief

Every delivery agent reads this before starting. It is deliberately short.

**Repository facts.** Python 3.13 only, `uv` for everything, `uv_build` backend,
single package at `src/bustan` (11,958 lines), 397 tests (13,006 lines), 6 example
projects each a standalone `uv` project, docs in `docs/`. Public surface is only
`bustan`, `bustan.errors` and `bustan.testing`; everything else is internal per
`docs/STABILITY.md` and may be restructured freely. `tests/unit/test_public_api.py`
asserts `bustan.__all__` as a 128-element tuple in exact order, and
`docs/API_REFERENCE.md` is generated and compared byte-for-byte in CI, so any export
change is a three-file edit: the module, that test, and a regenerated reference.

**Standards.**

- Clean code: no function beyond roughly 50 lines, no `Any` on a public signature,
  frozen slotted value types, tagged unions over stringly-typed discriminators, dead
  code deleted rather than commented out.
- Secure coding: deny by default, validate at the boundary, mask internal detail in
  any client-visible payload, never log a secret or an unescaped user string, bound
  every cache and buffer an unauthenticated caller can grow.
- Comments explain why and state invariants, never what the line does. Every public
  symbol gets a plain-English docstring, because those become the API reference.
  **Comments never reference anything outside this repository**: no external links, no
  issue numbers, no audit identifiers, no ticket ids. State the invariant where it
  holds, in full, in the code. Ticket and finding ids belong in commit messages and PR
  bodies only.
- Tests: every fix lands with a regression test. Use the shared request factory in
  `tests/conftest.py` once T-003 has merged; never add a fourteenth copy of
  `_build_request`.

**Verification block.** Run all of it before requesting review.

```bash
uv sync --group dev --frozen
uv run ruff format --check . && uv run ruff check .
uv run ty check src tests scripts
uv run pytest --cov=bustan --cov-report=term-missing
uv run python docs/audits/di-container-2026-09/run_repros.py
uv run python scripts/generate_api_reference.py --check
uv run python scripts/check_markdown_links.py
uv run python scripts/run_examples.py
```

From wave 3 onward add `uv run python scripts/check_layering.py`; from wave 3 also
`uv run python scripts/conformance_matrix.py`.

## Wave map

| Wave | Day | Release | Tickets | Parallelism |
| --- | --- | --- | --- | --- |
| 0a | 1 | - | T-001 | Serial, blocks everything |
| 0b | 1 | - | T-002, T-003, T-004 | 3 agents |
| S | 1 | **1.1.1** | T-010 | 1 agent, independent branch |
| 1 | 2 | **2.0.0-rc.1** | T-100..T-103 then T-104 | 4 agents, then 1 |
| 2 | 3 | **2.0.0-rc.2** | T-200..T-203 | 4 agents |
| 3 | 4 | **2.0.0-rc.3** | T-300, then T-301..T-305, then T-306 | 1, then 5 agents, then 1 |
| 4 | 5 | **2.0.0-rc.4** | T-400..T-403, T-405..T-407, then T-404 | 7 agents, then 1 |
| 5 | 6 | **2.0.0-rc.5** | T-500..T-504 | 5 agents |
| 6 | 7 | **2.0.0** | T-600..T-604 | 5 agents |

---

# Wave 0a - the sweep that must land alone

## T-001 Formatting and lint baseline

**Wave** 0a. **Depends on** nothing. **Blocks** everything.
**Owns** every file under `src/`, `tests/`, `scripts/`, `examples/`; `pyproject.toml`;
`.git-blame-ignore-revs`.

**Context.** `src/bustan/core/ioc/resolver.py` is tab-indented while the rest of the
package uses spaces, and `ruff format --check src` reports 40 of 94 files would be
reformatted. `[tool.ruff]` selects no lint rules beyond the default `E4,E7,E9,F`. If
this sweep does not land first, every later diff is buried in whitespace noise and
becomes unreviewable.

**Scope.** Run `ruff format` across the repository. Add
`[tool.ruff.lint] select = ["E","F","W","I","UP","B","SIM"]` and fix every violation
it surfaces, excluding `src/bustan/cli/templates` which is already excluded. Create
`.git-blame-ignore-revs` containing the formatting commit hash. Commit the format
sweep and the lint fixes as two separate commits so the mechanical one can be ignored
by blame.

**Also closes** QA-04, the stale narrative comments, dead branches and misleading
docstrings the audit catalogued, wherever the lint rules surface them. Delete dead
code rather than commenting it out, and delete a comment rather than updating it to
describe code that no longer needs describing.

**Must not touch.** Behaviour. This ticket changes no logic. A reviewer must be able
to confirm that by reading the diff.

**Acceptance.** `ruff format --check .` and `ruff check .` both clean; the test suite
passes unchanged at 397 tests; `.git-blame-ignore-revs` names the format commit.

---

# Wave 0b - the safety net

These three run in parallel. Disjoint file sets.

## T-002 Honest quality gates and release hygiene

**Wave** 0b. **Depends on** T-001. **Closes** QA-03, QA-08, QA-11.
**Owns** `pyproject.toml`, `.github/workflows/ci.yml`, `lefthook.yml`, `CODEOWNERS`,
`scripts/smoke_test_docs.py` (deletion).

**Context.** The coverage gate does not gate: `fail_under = 95` with the default
`precision = 0` means pytest-cov rounds 94.53 to 95 and exits zero while printing
`FAIL`. `[tool.uv.workspace] members = ["mini"]` names a directory that does not
exist. `scripts/smoke_test_docs.py` is referenced by nothing and its regex looks for a
README heading `## Five-Minute Quickstart` that was renamed to `## Quickstart`, so it
would fail immediately if wired up. `ty` runs on different paths in CI than in hooks.

**Scope.** Set `precision = 2` and move `fail_under` to the CI command line so
targeted local runs stop failing spuriously. Add a second coverage job gating
`bustan.core` at 95 percent branch coverage on its own. Add `ruff format --check` and
`uv lock --check` to CI and `lefthook.yml`. Delete the dead script. Align the `ty`
path lists. Add a `commit-msg` lefthook job enforcing Conventional Commits, since 33
of 98 historical commits are non-conventional and 7 produced no changelog entry. Add
`CODEOWNERS`. Add an advisory (non-blocking) CI job running
`docs/audits/di-container-2026-09/run_repros.py`; it becomes blocking in T-503.

**Acceptance.** Coverage gate fails on a deliberate one-line coverage drop, proven in
the PR body. `uv lock --check` passes. A non-conventional commit message is rejected
by the hook.

## T-003 Shared test fixtures

**Wave** 0b. **Depends on** T-001. **Closes** QA-16.
**Owns** `tests/conftest.py` (new); the 13 files defining `_build_request`; missing
`tests/**/__init__.py`.

**Context.** There is no `conftest.py` anywhere in the repository and exactly one
`@pytest.fixture` across 397 tests. `_build_request` is defined 13 times with six
distinct signatures; seven copies are byte-identical apart from the docstring. Six
test directories are missing `__init__.py`, which works today only because no basename
collides across those specific directories.

**Scope.** Write `tests/conftest.py` with one parameterised request factory
subsuming all 13 variants (method, path, path params, query, headers, cookies, JSON
body, raw body, app) plus an application factory helper. Delete every local copy and
repoint its call sites. Add the missing package markers.

**Acceptance.** No `def _build_request` remains under `tests/`. Suite passes at 397
tests. `grep -rc "def _build_request" tests/` returns zero.

## T-004 Stop the suite defending the defects

**Wave** 0b. **Depends on** T-001. **Closes** QA-12.
**Owns** `tests/unit/core/ioc/test_registry.py`, `tests/unit/core/ioc/test_resolver.py`,
`tests/integration/platform/test_exception_filters.py`,
`tests/unit/core/module/test_dynamic_modules.py`,
`tests/unit/testing/test_testing_builder.py`,
`tests/unit/core/module/test_metadata.py`.

**Context.** Six tests assert known-defective behaviour as the contract. A maintainer
who fixes the underlying defect sees a green test go red and reasonably reverts the
fix. Specifically: `test_registry.py:53-60` asserts a `use_value` provider silently
drops an explicit `scope`; `:73-79` asserts a raw `TypeError` rather than
`InvalidProviderError`; `test_resolver.py:53-71` asserts a non-controller,
non-request owner receives `RESPONSE` and `APPLICATION`;
`test_exception_filters.py:81-107` composes a request-scoped provider into a
default-scope controller and asserts only a 500; `test_dynamic_modules.py:34-49` and
`:114-136` accept a re-export and a token collision without resolving through them;
`test_testing_builder.py:101-115` locks in `close()` skipping the pre-shutdown stage;
`test_metadata.py:13-26` pins non-inheritance for module metadata while provider
metadata inherits.

**Scope.** Convert each to `pytest.mark.xfail(strict=True)` whose assertions state the
**intended** behaviour, with a comment naming the invariant that should hold. When the
corresponding fix lands in a later wave, that ticket removes the marker.

**Acceptance.** Six strict xfails, suite green, each xfail body asserting the target
contract rather than the current one.

---

# Wave S - the security patch

## T-010 Contain the cross-request identity disclosure

**Wave** S, runs concurrently with wave 0 on its own branch. **Depends on** nothing.
**Branch** `release/1.1.1` cut from the `v1.1.0` tag, not from `main`.
**Closes** RI-01, RI-02, RI-03, RI-04, RI-05, RI-09, RI-10, RI-12, CR-01, CR-06,
EX-04.
**Owns** on that branch: `src/bustan/core/ioc/resolver.py`,
`src/bustan/core/ioc/registry.py`, `src/bustan/core/ioc/scopes.py`,
`src/bustan/platform/http/controller_factory.py`, `src/bustan/addons/context.py`,
`src/bustan/pipeline/guards.py`, `src/bustan/pipeline/filters.py`, `SECURITY.md`,
`CHANGELOG.md`, `docs/REQUEST_SCOPED_PROVIDERS.md`, `docs/TROUBLESHOOTING.md`.

**Context.** These are the leaks an unauthenticated HTTP client can reach against
1.1.0 today. Users need protection now, on the 1.1 line, without waiting for the 2.0
rewrite. This patch is therefore deliberately surgical: **no formatting, no refactor,
no renames**, so it stays small enough to review and backport.

The mechanisms, each with a repro script under
`docs/audits/di-container-2026-09/repros/`:

- Controllers default to singleton scope and are cached after first construction, but
  the scope guard exempts every controller regardless of its declared scope and the
  special-token path hands any controller the live `Request` and `Response`. The
  controller's `@Controller(scope=...)` metadata is read and then never passed to the
  resolver. Documentation in three places promises a `ProviderResolutionError` here.
- A `{"provide": Iface, "use_class": Cls}` dict ignores `Cls`'s declared scope, so a
  request-scoped class bound under an interface token becomes a process-wide
  singleton.
- The scope guard rejects only `REQUEST` dependencies, so a singleton may capture a
  tenant-keyed durable instance; durable providers may inject `Request` and retain a
  stranger's headers for the life of the partition.
- Durable instances and their locks are never evicted and are keyed by whatever the
  provider derives from the request, so varying one header grows memory without bound.
- `request_context_id` is `str(id(request))`, and CPython reuses object ids: 200
  sequential requests produced 37 distinct ids and one id served five users.
- Guard rejections put the guard's dotted class path and the configured strategy name
  into the 403 body.

**Scope.** Pass `ControllerMetadata.scope` into instantiation as the owner scope and
delete the controller exemptions in both the guard and the special-token path; reject
durable-scoped controllers explicitly rather than falling through to the singleton
path. Default a `use_class` dict's scope from the class and raise when an explicit
dict scope is less strict. Reject durable dependencies of singleton owners and
`Request` injection into durable providers. Bound the durable store with an eviction
policy and release per-key locks after construction; compute the durable key once per
resolution and validate it is hashable. Generate a per-request id from `uuid4` stored
on request state. Return a generic `Forbidden` detail and keep the guard name in a
log field.

Ship with a `SECURITY.md` advisory naming the affected version and shapes, a changelog
entry, and corrections to the two documents that currently promise the unenforced
rule.

**Acceptance.** The named repro scripts report `FIXED`. Two requests with different
identity headers against a default-scope controller injecting a request-scoped
provider: the second never observes the first, proven by a new integration test. The
diff contains no formatting-only hunks.

**Note for the supervisor.** Two examples, `blog_api` and
`request_scope_pipeline_app`, use exactly the shape this ticket starts rejecting.
They are fixed in T-601, so `scripts/run_examples.py` fails on this branch until the
example modules are corrected in the same PR. Do that here rather than shipping a
release whose own examples do not run.

---

# Wave 1 - the resolution kernel (2.0.0-rc.1)

Twenty-nine findings live in one 931-line file with eight near-duplicate sync and
async method pairs that have already drifted. Patching costs more than replacing, so
the resolver becomes two phases with a hard boundary: **plan at bootstrap, execute at
runtime**. T-100 to T-103 build the pieces in parallel; T-104 assembles them.

## T-100 Provider normalization and token identity

**Wave** 1. **Depends on** wave 0. **Closes** PN-01, PN-02, PN-04, PN-06, PN-07,
PN-10, PN-11, MG-10.
**Owns** `src/bustan/core/ioc/registry.py`,
`src/bustan/common/decorators/injectable.py`, `src/bustan/core/module/compiler.py`,
`src/bustan/core/module/decorators.py`, and their unit tests.

**Context.** `normalize_provider` reads provider metadata with an inheriting `getattr`,
so registering an undecorated subclass of an `@Injectable` class silently binds the
**parent** under the parent's token; the child is never constructed and cannot be
resolved. The framework already has `_get_metadata(inherit=False)` and uses it for
module and controller metadata, so the correct pattern exists in the codebase. Cache
probes treat `None` as "not cached", so a singleton factory that legitimately returns
`None` re-runs on every resolution and an async one makes startup fail. Dict providers
silently ignore `inject` on `use_class`, silently prefer the first `use_*` key, and
turn `inject="dep"` into `("d","e","p")`. Bad scope strings escape as raw `ValueError`
rather than `InvalidProviderError`, and an unhashable token escapes as raw
`TypeError`. Registry dicts key on the raw token, so a `StrEnum` member and a bare
string of the same value are one key and shadow each other silently.

**Scope.** Read metadata from `__dict__` (or `_get_metadata(inherit=False)`) and bind
an undecorated subclass under its own identity or raise telling the author to decorate
it. Replace the provider metadata dict with a frozen `ProviderMetadata` carrying only
the scope, deriving token and target from the class. Introduce a private sentinel for
cache misses so `None` is a cacheable value. Validate dict shape: exactly one `use_*`
key, no unknown keys, no `inject` without `use_factory`, `inspect.isclass` on
`use_class`, `callable` on `use_factory`, reject `str`/`bytes` for `inject`. Require
durable bindings to be class bindings whose target has a classmethod or staticmethod
key hook. Translate every malformed input into `InvalidProviderError` naming the module
and the key. Canonicalise tokens type-aware so enum members stop aliasing strings, and
emit a diagnostic when a local binding shadows an imported export. Reject unordered
collections and bare dicts in `@Module`.

**Acceptance.** Named repro scripts `FIXED`. Property test over generated dict
providers: every invalid shape raises `InvalidProviderError` naming module and key.

## T-101 One source of visibility truth

**Wave** 1. **Depends on** wave 0. **Closes** MG-01, MG-02, MG-03, MG-07, MG-09.
**Owns** `src/bustan/core/module/graph.py`, `src/bustan/core/ioc/container.py`, and
their unit tests.

**Context.** Visibility is computed twice and the two implementations disagree in both
directions. `ModuleNode.available_providers` is local bindings plus direct imported
exports; `Container._build_bindings` recomputes the rule and adds global exports. A
globally exported token is resolvable but absent from the documented graph view, and a
module cannot export a globally visible token it can resolve. Worse, exports carry no
origin: re-exporting an imported token passes graph validation, maps the token to the
re-exporting module which holds no binding, and fails at the first request with
`Binding not found` and an HTTP 500. That is the standard facade pattern the framework
is modelled on. Colliding exports from two global modules resolve first-wins by
traversal order with no diagnostic, while the override manager refuses the same
ambiguity, so the app serves what the test harness will not override.

**Scope.** Compute visibility once in `build_module_graph` as a token to declaring
module mapping per node, following imported nodes so a re-export resolves to the true
origin, including global exports. Copy that one mapping into the registry; derive
`available_providers` and export validation from it. Raise `InvalidModuleError` when
two global modules, or two unshadowed imports, export the same token. Give a
module-class export a targeted error rather than a confusing provider error. Report a
cycle through a dynamic module with a readable path instead of a dataclass repr, and
delete the unreachable key-collision branch.

**Acceptance.** Named repro scripts `FIXED`. A two-hop re-export and a global facade
re-export both resolve through the importing module. A bootstrap check asserts every
visibility entry has a binding.

## T-102 Annotation resolution engine

**Wave** 1. **Depends on** wave 0. **Closes** RF-01, RF-02, RF-03, RF-04, RF-08,
RF-09, RF-11.
**Owns** new module `src/bustan/core/ioc/planning/annotations.py` and its tests.
**Must not touch** `resolver.py`; T-104 wires this in.

**Context.** Build this as a standalone pure function so it can be developed and
tested in isolation: given a class and a visibility mapping, return the resolved
dependency list or raise. The current behaviour it replaces:

- Type hints are evaluated with `globalns` taken from the **subclass's** module rather
  than the constructor's own `__globals__`, so an inherited `__init__` whose
  annotations name symbols imported only in the base module raises `NameError`.
- A synthesized namespace maps every visible token class by bare `__name__` and is
  passed as `localns`, which takes precedence over the constructor module's globals.
  A string annotation naming the module's own `Config` is silently rebound to any
  visible provider also called `Config`, and import order flips which one wins. With
  `from __future__ import annotations` in use throughout, every annotation is a string,
  so this applies everywhere.
- `Optional[X]` and `X | None` become opaque tokens; with `OptionalDep()` the planner
  injects `None` even though `X` is registered in the same module.
- `inspect.Parameter.default` is never read, so `def __init__(self, retries: int = 3)`
  fails with `builtins.int is not available`.
- `constructor.__globals__` is evaluated eagerly as a `getattr` default, so a provider
  inheriting a C-implemented `__init__` raises a raw `AttributeError`; a malformed
  string annotation raises a raw `SyntaxError`; the instance parameter is skipped by
  the literal name `self`; a second `Inject` marker silently wins.

**Scope.** Evaluate with the constructor's own `__globals__`, computed lazily.
Consult the synthesized namespace only for names lexical scope cannot resolve, and
raise naming the ambiguity when two visible tokens share a bare name. Unwrap unions
containing `NoneType` to the non-`None` member with `optional=True`. Honour parameter
defaults: when a token is not visible and a default exists, omit the argument. Skip
the first positional parameter by position. Raise on a duplicate `Inject`. Wrap every
introspection failure in `ProviderResolutionError`. Plan from `__new__` when `__init__`
is `object.__init__` and `__new__` is overridden.

**Acceptance.** Named repro scripts `FIXED` once T-104 wires it in; until then, unit
tests over generated module packages covering same-name collision, cross-module
inheritance, unions, defaults, and each malformed shape.

## T-103 Effective scope algebra

**Wave** 1. **Depends on** wave 0. **Closes** RI-06, RI-07, RI-08, RI-14.
**Owns** new module `src/bustan/core/ioc/planning/scopes.py` and its tests.
**Must not touch** `resolver.py`; T-104 wires this in.

**Context.** Also a standalone pure function: given the binding table, compute each
binding's effective scope and reject illegal edges, once, at build time. Today the
guard inspects only the direct dependency's binding and only for class constructors,
so three paths slip through. A factory's `inject` list is resolved with no owner-scope
check. A `use_existing` alias is forced to `TRANSIENT`, which is what the guard
inspects, while the alias re-resolves the request-scoped target. And
`push_request(None)` leaves the context variable untouched, so a provider constructor
that calls `app.get(...)` while an outer request is active silently receives
request-scoped state. Each leaks only when the lifespan does not run, which is the
normal condition in test suites. Separately, `INQUIRER` is read with no owner-scope
check, so a singleton records the first inquirer forever and startup succeeds or fails
depending on provider declaration order.

**Scope.** Compute effective scope transitively: `use_existing` inherits its target's
scope; a factory is at least as strict as every token in its `inject` list. Reject
singleton and durable owners that reach request scope, and singleton owners that reach
durable scope, with the error the documentation already promises. Reject or auto-promote
`INQUIRER` in a singleton. Allow `Request` for transient owners resolved inside a
request. Make imperative resolution entry points clear the active request explicitly.

**Acceptance.** Unit tests over a binding-table fixture asserting the computed scope
and the rejection message for every illegal edge, including factory and alias paths.

## T-104 Plan-then-execute kernel

**Wave** 1. **Depends on** T-100, T-101, T-102, T-103. **Closes** CR-05, MG-04,
MG-05, PN-09, QA-02, QA-14, and removes the xfails T-004 added for the resolver.
**Owns** `src/bustan/core/ioc/resolver.py` (replaced by
`src/bustan/core/ioc/planning/` and `src/bustan/core/ioc/runtime/`),
`src/bustan/core/ioc/container.py` public methods, `tests/unit/core/ioc/**`.

**Context.** The assembly ticket. Reflection currently runs per instantiation:
`inspect.signature`, `get_type_hints` and an O(visible tokens) namespace build, twice
per request for a request-scoped controller, measured at 194 microseconds at 31
visible tokens rising to 596 at 1501. Nothing validates transient or request-scoped
providers or controllers at bootstrap, so a missing dependency deploys cleanly and
becomes a 500 on the first request that touches it, while the same mistake on a
singleton is caught at startup. Dynamic module identity is `id()`-based although
`DynamicModule` is a frozen dataclass with value equality, so two equal `for_root`
calls produce duplicate instances and duplicate singletons.

**Scope.** Planning phase at container build: for every class binding and every
controller, produce an immutable plan using T-102 and T-103, verify every non-special
non-optional token is visible, and report **all** failures together from `create_app`
and `create_app_context`. Runtime phase: execute the plan with no reflection and no
namespace synthesis, one construction state machine per key shared by the sync and
async paths. Make dynamic module identity value-based with stable instance ids.
Rewrite the resolver's private-seam tests, which today make 29 direct calls to
underscore methods on hand-built registries and zero calls to the public API, as
black-box tests over a real module graph. Add the two-request isolation matrix from
the audit's testing strategy section: every owner scope crossed with every
request-derived dependency, run with and without the lifespan.

**Acceptance.** All wave 1 repro scripts `FIXED`. A benchmark in the PR body showing
per-instantiation cost is now flat in the number of visible tokens. Bootstrap rejects
a graph with a missing transient dependency and names every failure at once.

---

# Wave 2 - composition (2.0.0-rc.2)

Four parallel tickets, disjoint files.

## T-200 Lifecycle correctness

**Wave** 2. **Closes** OL-04, OL-05, OL-12, OL-13, OL-14, OL-15, OL-16, MG-06, QA-13.
**Owns** `src/bustan/core/lifecycle/**`, `src/bustan/app/lifespan.py`, the module
instantiation call in `src/bustan/pipeline/middleware.py`, and their tests.

**Context.** Hooks are dispatched by duck-typed `getattr` over every cached singleton
including `use_value` objects, so a class handed over as a value is called unbound and
crashes startup, a `MagicMock` receives all five hooks, and one object bound under two
tokens gets each hook twice. State is assigned only after every startup stage
succeeds, so a failure after `on_module_init` runs no teardown and leaks whatever was
opened; in the lifespan the startup await sits outside the `try`, so shutdown is not
even attempted. Aggregated teardown errors are rebuilt from `str()` with no `__cause__`
and no `ExceptionGroup`, although Python 3.13 is the floor. Durable instances are
excluded from warm-up and from every teardown stage. Shutdown leaves every cache
populated and startup is one-shot, so a closed context keeps serving destroyed
singletons. The `signal` argument is threaded through the whole API and no caller
supplies it.

**Scope.** Record instances as construction begins and tear down what has begun before
re-raising; move the startup await inside the lifespan `try`. Dispatch hooks only to
instances the container constructed, deduplicated by identity, naming the token in any
error. Include durable instances in teardown in reverse creation order. Raise an
`ExceptionGroup` carrying causes. Decide and document the post-shutdown contract:
either caches clear and startup may run again, or resolution raises after close. Wire
`signal` from the adapter's signal handling, or delete the parameter; T-403 supplies
the handlers, so coordinate through the supervisor.

## T-201 Override semantics

**Wave** 2. **Closes** OL-01, OL-06, OL-07, PN-03, PN-08, QA-15.
**Owns** `src/bustan/core/ioc/overrides.py`, override paths in
`src/bustan/core/ioc/container.py`, `src/bustan/core/ioc/tokens.py`, and their tests.

**Context.** Overrides are consulted only for the overridden token; provider
singletons, durable instances and request caches are untouched. Because the lifespan
eagerly builds every singleton, inside `with TestClient(app)` an override reaches only
controllers injecting the token directly, while every singleton depending on it keeps
the production object. A test can believe it swapped a database while the real one
keeps serving. Conversely a singleton first built during an override keeps the fake
after the block exits. The override manager matches tokens by identity while the
registry matches by equality, so a runtime-built string token resolves fine but cannot
be overridden and `has_override` silently returns `False`. Dynamic-module providers
cannot be targeted through the public `module_cls` parameter, and the ambiguity error
names a keyword that does not exist. Overridden providers receive no lifecycle hooks.

**Scope.** Make overrides bootstrap-only: registered before startup, raising a clear
error afterwards, and evicting transitive dependents when registered. Accept a module
class or a dynamic-module registration as the target, erroring only on genuine
ambiguity, and name the real parameter. Use equality-consistent token lookup via an
index maintained by the registry. Treat an override of a singleton binding as the
singleton instance so hooks run. Document `InjectionToken` identity semantics.

## T-202 Testing surface delegates to the lifecycle

**Wave** 2. **Closes** OL-03, OL-08, and removes the T-004 xfail for the builder.
**Owns** `src/bustan/testing/**`, `tests/unit/testing/**`,
`tests/integration/testing/**`.

**Context.** `bustan.testing` is a documented stable surface that re-implements
lifecycle orchestration and has drifted. `compile()` calls the hook runners directly
instead of `LifecycleManager.startup()`, skipping the async-factory warm-up, so any
graph with an async singleton factory raises `uses an async factory. Initialize the
application before resolving it synchronously`. `close()` never runs
`before_application_shutdown`, has no closed flag so a second call re-runs hooks,
raises only the first error, and leaves the manager unaware, so
`compiled.application.close()` is a no-op while `application.init()` runs init hooks a
second time. Class and factory replacements are resolved from the root module, so a
fake with the same constructor as the provider it replaces fails unless every
dependency is exported to the root, with an error blaming the wrong module.

**Scope.** Register value overrides then delegate to `LifecycleManager.startup()` and
`shutdown()`. Build replacements from the declaring module through the async paths.
Delete the hand-rolled stage sequencing.

## T-203 Global pipeline providers resolve per request

**Wave** 2. **Closes** OL-02, OL-09, OL-10, OL-11, RF-05, RF-06, RF-07, RF-10, PN-05.
**Owns** `src/bustan/platform/http/compiler.py` global-provider path,
`src/bustan/platform/http/controller_factory.py`, `src/bustan/addons/**`,
`src/bustan/app/application.py`.

**Context.** The route compiler resolves `APP_GUARD`, `APP_PIPE`, `APP_INTERCEPTOR`
and `APP_FILTER` once inside `_create_app`, before the application exists and before
any lifespan, and bakes the instances into every route contract. Overrides applied
afterwards are a silent no-op while `has_override` reports `True`, so a test that
believes it disabled a global guard is lying. Only one binding per token per module is
allowed, a request-scoped global guard cannot exist, and one depending on an async
factory fails at `create_app` with no earlier point to initialize.

Related: async factories work only for singleton scope because the container exposes
no async instantiation and the request path is synchronous, so a request-scoped async
factory returns 500 with a misleading hint. Three different predicates decide whether
a factory is async, so a callable object with `async __call__` is never warmed and
leaks an un-awaited coroutine. The active request is pushed only for the duration of a
resolve call, so `ModuleRef.get` of a request-scoped provider fails inside a handler
even though a request is in flight, and the `ApplicationContext.get` docstring points
users at an alias that fails identically. `APPLICATION` resolves to three different
types depending on entry path, which is why `ModuleRef` and `DiscoveryService` raise a
raw `TypeError` under the documented non-HTTP context.

**Scope.** Resolve `APP_*` providers lazily per request through the component
resolver, which already supports request-scoped components, with list bindings for
multiple providers per token. Expose async instantiation on the container and route
request execution through it. Compute `Binding.is_async` once at normalization and use
it everywhere, closing the coroutine on error. Normalise `APPLICATION` to one type on
every path and accept `ApplicationContext` in the addons. Push the native request for
the whole route execution and add a request-aware public resolution entry point. Fix
the `hasattr` fallback that leaks a `KeyError`. Rewrite the misleading docstring.

---

# Wave 3 - ports and adapters (2.0.0-rc.3)

T-300 lands first and alone; T-301 to T-305 then run in parallel.

## T-300 The contracts package

**Wave** 3, serial. **Depends on** wave 2.
**Owns** new `src/bustan/contracts/`; moves the neutral types out of
`src/bustan/platform/http/abstractions.py`.

**Context.** The neutral abstractions module is itself the largest Starlette consumer
outside the adapters. `as_http_request` does an `isinstance` check against Starlette
and `to_starlette_response` constructs Starlette responses, both as free functions in
the supposedly neutral module and both exported from its `__all__`. The request side
is a thin proxy that leaks native objects out of `url`, `query_params`, `state` and
`app`; the response side is three plain dataclasses with no Starlette awareness and is
already refactor-ready.

**Scope.** Create `src/bustan/contracts/` holding every Protocol and neutral value
type and importing nothing from the rest of the package: the request protocol with a
**declared mutable state namespace** rather than an untyped `Any`, neutral URL and
multidict types so native objects stop leaking, the response value types, the adapter
port, and the extension protocols. Move `StarletteHttpRequest` and
`to_starlette_response` out; T-301 rehomes them. Add the missing `__init__.py` to the
seven directories that lack one and give every package an explicit `__all__`.

## T-301 Narrow the adapter port

**Wave** 3. **Depends on** T-300. **Closes** QA-01, QA-07, QA-10, RI-13, EX-03.
**Owns** `src/bustan/platform/http/adapter.py`, `routing.py`, `abstractions.py`,
`responses.py`, `execution.py` transport bits, `src/bustan/adapters/starlette/`,
`src/bustan/pipeline/middleware.py`, `src/bustan/security/throttler.py` state bits.

**Context.** The port leaks in both directions. `compile_routes` is handed the DI
container, so every adapter must know about the container, execution plans and the
middleware registry: the opposite of a thin transport seam. `__call__(scope, receive,
send)` bakes ASGI into the contract. There is no abstract method for either
conversion an adapter actually owes. `platform/http/routing.py` is named neutrally,
lives outside the adapter package, and imports **from** it, which is a layering
inversion; it also duplicates the host-routing capability check and emits the version
dispatch 404 as a native response. The public middleware base class is typed in
Starlette terms, so every application that subclasses it is coupled. Request-scoped DI
caches are stashed on Starlette's `request.state`, and the throttler communicates with
the response writer through four untyped attributes on the same object. The route
middleware chain runs outside the request-scope lifetime, so a middleware resolving a
request-scoped provider after `call_next` gets a second instance and silently loses
request-local state.

**Scope.** Redefine the port: the framework compiles a neutral route plan and owns
execution; the adapter translates transport and manages server lifecycle, via
`from_native_request`, `to_native_response`, `start`, `stop` and `create_test_client`,
with no container parameter. Move `StarletteHttpRequest`, `to_starlette_response`,
the Starlette half of `routing.py` and `ConditionalMiddleware` into
`src/bustan/adapters/starlette/`. Split the neutral routing plan out. Neutralise the
public middleware base class. Replace the `request.state` side channels with typed
per-request slots on the contract. Clear request state at the outermost boundary,
after the middleware chain returns, not inside route execution. Give
`execute_http_exception` the same error handling as the main path so the middleware
failure path stops returning a different content type and, under `debug`, a DI
traceback.

## T-302 The proof adapter

**Wave** 3. **Depends on** T-300.
**Owns** new `src/bustan/adapters/asgi/` and its tests.

**Context.** No second adapter has ever existed, so nothing has tested the
abstraction. The only direct subclass of the port in the test suite calls `super()` on
every method for coverage. This adapter exists to fail loudly the moment a coupling
regresses; it is a permanent maintenance commitment, not a demo.

**Scope.** A dependency-free adapter over raw ASGI implementing the T-301 port:
routing, path parameters, body reading, streaming and file responses, lifespan, and a
test client. It must import no third-party web framework.

## T-303 A conformance matrix that means something

**Wave** 3. **Depends on** T-300. **Owns** `src/bustan/platform/http/conformance.py`,
new `scripts/conformance_matrix.py`, `.github/workflows/ci.yml` conformance job.

**Context.** The suite is two checks (a health route and a body binding) and it drives
the adapter under test with Starlette's own test client, so a non-Starlette adapter
could not be certified by it.

**Scope.** Cover every parameter source, every response strategy, all three
versioning strategies, middleware, exception filters and lifespan. Drive each adapter
through its own `create_test_client`. Run the matrix against both adapters in CI and
require identical results.

## T-304 Enforce the layering

**Wave** 3. **Depends on** T-300. **Owns** new `scripts/check_layering.py`, CI job.

**Context.** Separation of concerns has to be checkable or it decays. Starlette is
referenced 56 times across 23 files today precisely because nothing objected.

**Scope.** Walk the import graph and fail when `contracts`, `kernel`, `runtime` or
`pipeline` imports a web server, or when any package imports a layer above it. Allow
the adapter packages. Follow the existing `scripts/` conventions: a `--check` mode,
clear failure output naming file and line, and a unit test loading it by path the way
the other script tests do.

## T-305 Starlette becomes an extra

**Wave** 3. **Depends on** T-301, T-302. **Owns** `pyproject.toml` dependency tables,
`src/bustan/app/bootstrap.py` adapter selection, `scripts/package_smoke_check.py`.

**Context.** `starlette` and `uvicorn` are unconditional runtime dependencies and
`bootstrap.py` imports the Starlette adapter at module scope, so importing `bustan` at
all imports a web server. The `debug` and `lifespan` arguments bypass the port
entirely because the port has no constructor contract.

**Scope.** Move both to a `starlette` extra, select the adapter lazily with a clear
error naming the extra when none is installed, and give the port a construction
contract so `debug` and `lifespan` reach a custom adapter. Extend the smoke check to
install without extras and confirm the kernel imports with no web server present.

## T-306 The package layout move

**Wave** 3, serial, last. **Depends on** T-301 through T-305 all merged, **and on
two further gates recorded below**.
**Blocks** every wave 4 and wave 5 ticket, which reference the new paths.
**Owns** every file under `src/bustan/` for the purpose of moving it and rewriting
imports; `pyproject.toml` packaging entries; `tests/` import lines;
`scripts/check_layering.py` allow list.

**Context.** Waves 1 to 3 fix behaviour and introduce `contracts/` and `adapters/`,
but the remaining package names still describe the old shape. `core/` holds the
injection kernel that must never see a web server; `platform/http/` holds
transport-neutral request execution that is no longer platform-specific once T-301
has moved the Starlette parts out; `logger/` holds observability that is much more
than logging. The names should say what the layering rule enforces, so that the next
contributor reads the constraint from the directory tree before working against it.

This is the second mechanical sweep of the programme and, like T-001, it must land
alone. It changes no behaviour: a reviewer must be able to confirm that by reading
the diff.

**Target layout**, which `scripts/check_layering.py` from T-304 then enforces:

```
src/bustan/
  contracts/     Protocols and neutral value types. Imports nothing.
  kernel/        was core/. Injection, modules, lifecycle. Imports contracts only.
  runtime/       was platform/http/ minus adapters. Neutral request execution.
  adapters/      starlette/ and asgi/. The only packages that may import a server.
  pipeline/  security/  observability/ (was logger/)  configuration/ (was config/)
  openapi/  testing/  cli/  health/
```

**Scope.** Perform the moves, rewrite every import, update the packaging
configuration, and extend the layering script's allow list to the new names. Public
imports from `bustan`, `bustan.errors` and `bustan.testing` must be unchanged, which
the existing public-API test proves. No behavioural edit of any kind travels with
this ticket; if you find a bug while moving a file, report it, do not fix it here.

**Acceptance.** Full verification block green with no behavioural diff; the public
API test and the byte-exact API reference check both pass untouched;
`scripts/check_layering.py` passes against the new tree; a second
`.git-blame-ignore-revs` entry names the move commit.

**Two gates before this ticket may be dispatched.** Both were found after the ticket
was written, and neither is satisfied by anything inside this ticket's own scope.

*Gate one: the rc.2 follow-up set must be closed first.* This move renames `core/` and
`platform/http/`, and nine of the ten open rc.2 follow-ups name paths under those two
directories in their own `Owns` lists. Dispatching this ticket first turns nine ticket
`Owns` lists into fiction in a single commit, and file ownership is the only thing that
lets blind agents share the repository. The rc.2 set runs first; this ticket waits.

*Gate two: the layering check has to be able to pass.* The acceptance criterion above
says `scripts/check_layering.py` passes against the new tree. The check landed reporting
violations that a rename does not remove - an import edge survives its file being moved -
and this ticket forbids the behavioural edits that would close them. So either those
violations are closed by the tickets that own the files, or this criterion is unreachable
and has to be rewritten to say the report is no worse than it was. Decide which before
dispatch, not during.

---

# Wave 4 - request contract and operability (2.0.0-rc.4)

Path note: every ticket below refers to the post-T-306 layout. `runtime/execution.py`
is the file that was `platform/http/execution.py`, and `observability/` was `logger/`.

Eight parallel tickets. This wave turns a framework that runs into one that runs in
production.

## T-400 One error contract for the request path

**Wave** 4. **Closes** EX-01, RI-11. **Owns** `src/bustan/runtime/execution.py`
(formerly `platform/http/execution.py`).

**Context.** The controller and, transitively, every request-scoped provider are
constructed before the execution context exists and before observability starts; the
pipeline is resolved before guards run. The except branch calls the filter chain only
when both a context and a resolved pipeline exist, so any exception from a constructor
returns a hard-coded 500 that no route filter, no `APP_FILTER` and no metrics hook ever
sees. The documentation recommends putting the authenticated principal in a
request-scoped provider, which is exactly the code that raises authentication and
validation errors in a constructor. Because guards run after construction, an
anonymous request rejected with 403 has already executed those constructors and left
the durable partition it named in the cache; with a 0.2 second durable constructor,
five concurrent anonymous requests raised an unrelated route from 2 milliseconds to
811.

**Scope.** Build the context before instantiation, start observability first, resolve
and run guards before constructing request-scoped and durable dependencies, and fall
back to the global filter chain whenever a context exists. Evict partitions created by
a request that ends in rejection. Remove the T-004 xfail for the exception-filter test
and assert the mapped status instead.

## T-401 A usable exception hierarchy

**Wave** 4. **Closes** EX-02, EX-04 on the 2.0 line.
**Owns** `src/bustan/core/errors.py`, `src/bustan/errors.py`,
`src/bustan/pipeline/filters.py`, `src/bustan/pipeline/guards.py`,
`src/bustan/runtime/compiler.py` policy validation.

**Context.** Only four statuses are reachable through the framework's error model:
400, 403, 429 and 500. There is no `HttpException`, so an application cannot return a
404 except by returning a raw response. Every guard rejection maps to 403 including
"Authentication required", which breaks OAuth and OIDC refresh flows that key on 401
with `WWW-Authenticate`. The 403 body enumerates internal role and permission names to
unauthenticated callers. The problem-details `type` is always `about:blank` and `code`
is never populated, which defeats the point of RFC 7807. A broken
`AUTHENTICATOR_REGISTRY` wiring surfaces as a 403 on every authenticated route, so a
misconfiguration is indistinguishable from a genuine auth failure.

**Scope.** Add an `HttpException` hierarchy covering the common statuses with a
documented problem-type URI per class and a populated `code`. Return 401 with
`WWW-Authenticate` for missing credentials. Stop echoing role and permission names.
Validate at compile time that the authenticator registry is visible from every route
carrying an auth policy and resolvable synchronously.

## T-402 Health and readiness

**Wave** 4. **Owns** new `src/bustan/health/`.

**Context.** Absent. `/health` appears only in a test fixture and a documentation
example. Every Kubernetes deployment needs liveness and readiness on day one, and
readiness must reflect lifecycle state so a pod is not routed traffic before startup
hooks finish or during drain.

**Scope.** A health module with an indicator protocol, aggregation across registered
indicators, distinct liveness and readiness semantics, readiness tied to lifecycle
state and to the drain flag T-403 introduces, and a documented response shape.

## T-403 Graceful shutdown

**Wave** 4. **Owns** `src/bustan/adapters/starlette/` server lifecycle,
`src/bustan/app/application.py` `listen`.
**Inherits** the lifecycle shutdown signature from wave 2, already merged: read
`LifecycleManager.shutdown` in your checkout and pass the signal name it expects. If
that parameter is absent, the earlier ticket removed it deliberately; wire the drain
sequence without it and say so in your PR rather than reinstating it.

**Context.** `StarletteAdapter.close()` is `pass`, so `Application.close()` never stops
a running server. `listen` constructs a uvicorn server with no graceful-shutdown
timeout, no signal handling and no in-flight tracking, so a rolling deploy drops
in-flight requests. The lifecycle API threads a `signal` argument that no caller ever
supplies, so hooks always receive `None`.

**Scope.** Install signal handlers in `listen`; on signal, flip readiness, drain
in-flight requests within a configurable timeout, then run shutdown with the signal
name. Implement `stop`. Document the sequence.

## T-404 Request limits

**Wave** 4. **Depends on** T-400 merged, because both tickets change
`runtime/execution.py` and yours is dispatched only once T-400 has landed.
**Owns** `src/bustan/runtime/execution.py` timeout wrapper,
`src/bustan/runtime/params.py` body and upload limits.

**Context.** Body reading calls `json()`, `form()` and `body()` with no size check and
no `Content-Length` guard, and the upload markers have no size or count cap, so a
single large POST is an out-of-memory vector. There is no timeout anywhere, so a slow
handler occupies a worker indefinitely. Sync handlers go to anyio's default 40-thread
limiter, which is never configured or exposed, making it an invisible concurrency
ceiling.

**Scope.** Configurable request timeout returning 503 or 504 through the filter chain;
body-size and upload-count limits returning 413; an exposed, configurable thread
limiter for sync handlers.

## T-405 Real observability

**Wave** 4. **Owns** `src/bustan/observability/` (formerly `logger/`),
`src/bustan/__init__.py` observability exports.

**Context.** `finish_request` takes only a status code and an error, so **request
duration is not measured at all** and no latency percentile can be computed: the most
important service-level metric is unavailable. There is no correlation id, no
`traceparent` handling, and no way to stitch a distributed trace. The framework logger
writes an f-string through `print()` with no JSON, no fields, no redaction and no
newline escaping, so a user-supplied string containing a newline forges log records.
Its override is a plain class attribute, so a test override leaks process-wide across
concurrent requests, unlike the observability hooks which correctly use a context
variable. Two parallel logging systems exist: this one and stdlib `logging` used by
the execution engine and the filters. The bespoke tracer protocols do not match
OpenTelemetry, and none of the sinks are exported, so the only supported way to attach
a metrics backend does not exist on the supported surface.

**Scope.** Record duration and pass it to the sink. Generate or accept a correlation
id and attach it to every log record and span. JSON-structured logging on stdlib
`logging` with redaction of configured keys and newline escaping. Reshape the tracer
protocols to OpenTelemetry's span model with context propagation and head sampling.
Move the logger override to a context variable. Export the sinks and accept them
through `create_app`.

## T-406 Throttler hardening

**Wave** 4. **Owns** `src/bustan/security/throttler.py` and its tests.

**Context.** Storage is a plain dict on the instance, so with N workers the effective
limit is N times the configured one. It is a fixed window, keys are never evicted so
an attacker rotating source addresses grows memory without bound, there is no
`Retry-After` on the 429, and the key is the raw connection address, so behind a load
balancer every request shares one bucket.

**Scope.** A storage protocol suitable for a shared backend with an in-memory
implementation that evicts; a sliding window; `Retry-After`; a key derived from
trusted proxy headers with a configurable trusted-proxy list.

## T-407 Decorators that keep their promise

**Wave** 4. **Owns** `src/bustan/security/policy.py`, `src/bustan/pipeline/metadata.py`
policy objects, and whichever runtime module implements the chosen behaviour.

**Context.** This is the finding most corrosive to enterprise trust. `@Cache`,
`@Idempotent` and `@Audit` are defined, compiled into the policy plan, and then read
only by a "does this route have any policy" check and the governance report. Nothing
caches, nothing deduplicates an idempotency key, nothing writes an audit record. An
adopter who writes `@Audit(event="user.delete")` and ships it to production has no
audit trail. Separately, `@RateLimit(limit=, window=)` compiles its arguments and the
throttler reads only the `skip` flag, so per-route limits silently do nothing.

**Scope.** This ticket is deliberately split into two pull requests, because the
choice between implementing and de-claiming is a product decision the supervisor must
make and you cannot ask for it directly.

**First PR, no production code.** A draft PR whose description begins with
`DECISION REQUIRED:` and sets out, for each of the four decorators, what implementing
it would take, what de-claiming it would cost an adopter who is already using it, and
your recommendation. Include the per-route rate-limit wiring as code in this PR, since
that one is unambiguously a bug and needs no decision. Then stop.

**Second PR, after the supervisor rules in a review comment.** Implement the decision,
with docstrings that state plainly what each decorator does and does not do, and a
changelog entry that calls out the correction in either direction.

---

# Wave 5 - performance, parity, public surface (2.0.0-rc.5)

## T-500 Stop re-resolving the pipeline per request

**Wave** 5. **Closes** CR-02, CR-03, CR-04. **Owns** `src/bustan/runtime/execution.py`,
`src/bustan/runtime/controller_factory.py`, `src/bustan/kernel/injection/runtime/`.

**Context.** The pipeline is resolved from the container on every request even though
the execution plan is compiled once and frozen: for a route with a global pipe, two
guards and a filter that is four container resolutions per request that could be zero.
A throwaway response object is allocated per request purely as a header scratchpad and
then copied. A new execution context is allocated per handler parameter. Separately,
the sync and async construction paths use different lock families so a singleton can
be built twice and the loser discarded with no teardown, leaking whatever it opened,
and request-scoped cache writes have no check-and-set so concurrency inside one
request yields two instances, contradicting the documented one-per-request contract.

**Scope.** Memoize the resolved pipeline on the execution plan, invalidated by the
bootstrap-only override rule from T-201. Remove the scratchpad allocation. Unify the
construction lock discipline. Use check-and-set for the request cache.

## T-501 Benchmarks and a regression gate

**Wave** 5. **Owns** new `benchmarks/`, `pyproject.toml` dev dependency, CI job.

**Context.** The repository contains no benchmark, no profiling harness and no
performance test of any kind. A framework positioned for mission-critical use has no
evidence of its own throughput or latency, and no way to notice a regression.

**Scope.** `pytest-benchmark` covering a simple route, a route with pipeline
components, a request-scoped chain and container resolution. Publish a baseline. Add a
CI job that fails on regression beyond a stated threshold.

## T-502 NestJS parity gaps

**Wave** 5. **Closes** DP-01, DP-02, DP-03, MG-08. **Owns** `src/bustan/addons/module_ref.py`,
`src/bustan/core/module/builder.py`, `src/bustan/core/module/compiler.py` dynamic
merge, `src/bustan/core/ioc/planning/` inquirer handling.

**Context.** `ModuleRef` injected through DI is always root-scoped regardless of which
module's provider received it, and `strict=False` also resolves against the root
rather than searching the container, so a child module's service cannot resolve its own
non-exported providers by either route. `for_root_async` cannot see the importing
module's providers because the generated dynamic module carries no imports. A dynamic
module cannot override a token its base module declares, because providers are
concatenated and then rejected as duplicates. `INQUIRER` yields the requesting class
rather than the instance, and a dict entry in a factory inject list crashes with an
unhashable-type error rather than a framework error.

**Scope.** Host-module scoping for `ModuleRef` with a genuine container-wide
non-strict lookup and an ambiguity error. Add `imports` to the async builder methods.
Let dynamic providers replace base providers with the same token, documented. Yield
the instance for `INQUIRER`. Validate inject entries.

## T-503 Public surface and stability policy

**Wave** 5. **Closes** QA-05, QA-06, QA-09. **Owns** `src/bustan/__init__.py`,
`src/bustan/core/ioc/registry.py` typing, `docs/STABILITY.md`,
`tests/unit/test_public_api.py`, `docs/API_REFERENCE.md` regeneration, CI repro gate.

**Context.** Six extension points an enterprise must customise live only in namespaces
the project's own stability document declares internal and changeable without
deprecation: the authenticator, the observability sink, the HTTP adapter, the response
serializer, the ten policy decorators and the problem-details filter. Meanwhile
`CorsOptions`, `ThrottlerModule` and `ConfigService` are exported, so the export set is
inconsistent with the policy rather than derived from it. `Container.resolve` returns
`object`, `ApplicationContext.get` returns `Any`, and `InjectionToken[T]` is generic
but drives no inference, despite the package claiming `Typing :: Typed`. Registry and
cache internals are public mutable dicts reachable through the documented
`app.container`.

**Scope.** Promote the six extension points, add overloads so `get(InjectionToken[T])`
returns `T` and `get(type[T])` returns `T`, expose read-only views of registry and
caches, and rewrite `docs/STABILITY.md` so the export set and the policy agree.
Regenerate the API reference and update the exact-order export tuple. Flip the repro
harness CI job to blocking: every one of the 91 findings must report `FIXED`.

## T-504 Operator tooling

**Wave** 5. **Owns** `src/bustan/cli/**`.

**Context.** The CLI has strong governance commands but no diagnostics. There is no
`--version`. The dependency-graph data already exists behind `DiscoveryService`, which
returns modules with their imports, controllers, providers and exports, and per-provider
scope and resolver kind, but no command surfaces it. Commands catch only four exception
types, so a `ProviderResolutionError` from importing the user's root module escapes as
an unhandled traceback.

**Scope.** `bustan doctor` scanning a codebase for constructs 2.0 changes and printing
the specific fix for each, which is the migration tooling the clean-break decision
depends on. `bustan graph` over the existing discovery data. `bustan config --redacted`,
once T-405 supplies redaction. `--version`. A `--format table|json` option. Catch
`BustanError` and report cleanly.

---

# Wave 6 - documentation and release (2.0.0)

## T-600 Rewrite the behavioural documentation

**Owns** `docs/REQUEST_SCOPED_PROVIDERS.md`, `docs/LIFECYCLE.md`,
`docs/REQUEST_PIPELINE.md`, `docs/PLATFORM_INTEGRATION.md`, `docs/TROUBLESHOOTING.md`,
`README.md`.

**Context.** The audit found three places where the documentation already contradicts
the code, and waves 1 to 5 change most of the behaviour these documents describe.
Every rule the container enforces should have a sentence here and a test; every rule
these documents state should be enforced.

## T-601 Examples

**Owns** `examples/**`, `scripts/run_examples.py`, `.github/workflows/ci.yml` examples
job.

**Context.** Two of six examples use the exact shape wave S starts rejecting. Each
example ships its own test file with real assertions that nothing ever runs: not
`run_examples.py`, which only checks the exit code, and not the root test suite, whose
paths do not reach them. The example build backend pins are a major behind the root.

**Scope.** Update all six to 2.0 patterns, run their test files in CI, and align the
pins.

## T-602 Migration guide and new documentation

**Owns** new `docs/MIGRATION_1x_to_2x.md`, `docs/ARCHITECTURE.md`,
`docs/OBSERVABILITY.md`, `docs/SECURITY_HARDENING.md`, `docs/DEPLOYMENT.md`,
`docs/README.md` index.

**Context.** The clean-break decision means a 1.x application will not start on 2.0
until it is corrected. The guide plus `bustan doctor` from T-504 is what makes that
acceptable. `ARCHITECTURE.md` documents the layering rule and why it is enforced by
CI, so the next contributor understands the constraint before working against it.

## T-603 Repository consistency

**Owns** `CHANGELOG.md`, `CONTRIBUTING.md`, `docs/VERSIONING.md`, `release/config.json`,
`release/manifest.json`.

**Context.** The "1.0.0 and 1.0.1 were accidental, 2.0.0 is the real one" statement
appears in four files plus the README and must now change everywhere at once.
`CHANGELOG.md` has a hand-written tail below the content the retired release bot
generated. The `bustan-governance` release-gate configuration in the release files is
read by the `bustan governance release-gate` command and by no workflow.

**Scope.** Reconcile the status statements, remove the stale tail, and either wire the
governance gate into CI or delete it before it becomes load-bearing folklore.

## T-604 Release 2.0.0

**Owns** the release. Supervisor-run.

**Scope.** Full verification block plus the conformance matrix on both adapters plus
the blocking repro gate; confirm the kernel imports with no web server installed;
compose the changelog entry from the milestone's closed issues, land it with the version
bump, tag the merged commit; verify the published artifact through the existing
post-publish workflow.

---

## Coverage of the audit

Day 1 closes 16 findings, wave 1 closes 33, wave 2 closes 22, wave 3 closes 5, wave 4
closes 3, wave 5 closes 11. Every one of the 91 has a named owning ticket; QA-04 is
carried by T-001, where the lint sweep surfaces it.

`run_repros.py --expect-fixed` is the arbiter, not that table. A finding is closed
when its script reports `FIXED` and a regression test has replaced it. The harness
runs advisory from T-002 and blocking from T-503, so drift between this plan and
reality surfaces immediately.

## Risks

- **Wave 1 has the least slack.** Waves 2 to 5 build on the kernel. If T-104 slips,
  the supervisor should ship rc.1 with T-100 to T-103 merged and T-104 held, rather
  than compressing its test matrix.
- **T-407 is a product decision.** Whether to implement or de-claim the decorative
  decorators changes the 2.0 feature story. Escalate early.
- **The proof adapter is a permanent commitment.** If it leaves the conformance
  matrix it rots into a false portability claim, which is the exact failure this
  programme corrects.
- **File ownership is the whole safety mechanism.** An agent that edits outside its
  `Owns` set silently breaks a sibling ticket. The supervisor checks this on every PR
  before reading the logic.
