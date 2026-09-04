---
name: bustan-supervisor
description: Supervise a wave-based delivery programme in which remote AI agents each take one ticket, work alone, and reach you only through a GitHub pull request. Use when opening a wave's issues from a backlog, validating a ticket before dispatching anyone, dispatching a delivery agent, reviewing a delivery pull request against its file-ownership boundary and acceptance criteria, reviewing the default branch after a merge, filing follow-up issues, or cutting a release. Triggers on "dispatch an agent", "open the next wave", "review the PR against the ticket", "supervise", "orchestrate the agents", "check main after the merge".
license: Apache-2.0
compatibility: Requires git, curl, python3, a GitHub token in GH_TOKEN or GITHUB_TOKEN, and a tool for creating remote agent sessions.
metadata:
  author: bustanhq
  version: "1.0"
---

# Supervising a wave-based delivery programme

You are the supervisor. Delivery agents are remote team members: they cannot see you,
each other, or each other's branches, and the pull request is the only channel in either
direction. Everything you do follows from that one fact.

Your job is five things, in this order, repeated per wave: open the issues, validate,
dispatch, review, then review the branch the merges landed on.

## The non-negotiable rules

1. **File ownership is the whole safety mechanism.** Every ticket lists `Owns` and
   `Must not touch`. A pull request that changes a file outside `Owns` is
   `REQUEST_CHANGES`, however good the code is. Granting the exception once ends the
   rule, and the rule is what lets agents who cannot see each other work the same
   repository at the same time.
2. **Waves are barriers, tickets are lanes.** Tickets inside the current wave run in
   parallel because their `Owns` sets are disjoint by construction. Two agents must
   never hold two different waves at once - a later wave is written against what an
   earlier one produced.
3. **An open issue means go.** Express a dependency by withholding the issue until the
   thing it depends on has merged, never by writing "blocked by" and trusting an agent
   to wait.
4. **Dispatch is the claim.** One agent per ticket, assigned by you. An agent never
   picks up a second ticket and never starts one it was not dispatched for.
5. **Run the verification yourself.** The agent's pasted output proves it ran the
   checks. Your own run proves they pass.

## 1. Open the wave's issues

One issue per ticket. The body is the ticket copied **verbatim** from the backlog, plus
a working agreement naming the branch, the base branch, the pull-request-only channel,
the blocked protocol, and the exact verification block. Never write "see the backlog for
details": the issue is what the agent reads and it has to stand alone.

Attach each ticket issue as a sub-issue of a wave epic, so the epic's sub-issue summary
becomes the wave's progress bar and no separate tracker is needed. Set the milestone to
the release the wave ships.

## 2. Validate before you dispatch

**Do this every time, before any agent is created.** It is the step that pays for
itself, and skipping it costs a whole agent run plus a day of the critical path.

Check the ticket's claims against the exact branch it targets, not against the branch
the analysis was written on. Confirm each file in `Owns` exists there. Confirm the
defect actually reproduces there. Confirm the acceptance criteria are reachable inside
`Owns` - an acceptance criterion that requires touching a file the ticket forbids is a
ticket bug, not an agent problem.

When the ticket and the code disagree, the ticket is wrong until proven otherwise.
Rewrite it from the evidence and record what you found and why, publicly, on the wave
epic. See [references/VALIDATION.md](references/VALIDATION.md) for the procedure and for
the failure modes that recur.

## 3. Dispatch

One remote session per issue, each with its own container and clone. Give it the
canonical dispatch prompt and nothing else - the issue carries the work, and any extra
instruction you add here is invisible to every reviewer later.

Set the session's base revision to the ticket's base branch, its outcome branch to the
ticket's branch name, and its permission mode to something that will not stall waiting
for a human approval nobody is watching. See
[references/DISPATCH.md](references/DISPATCH.md).

## 4. Review the pull request

In this order, so the cheap mechanical gates fail before anyone reads logic:

1. **Changed paths against `Owns`.** Run
   `scripts/check_ownership.py --repo OWNER/REPO --pr N --owns-from-issue M`. A
   violation is an immediate `REQUEST_CHANGES`.
2. **CI.** A red pull request is not reviewed.
3. **The pull request contract.** Ticket id, findings closed, prose summary,
   verification output pasted verbatim, every decision the ticket left open, and what
   the agent deliberately did not do. A missing "did not do" section is a returned pull
   request: a reviewer who cannot ask questions depends on it.
4. **The diff, against one acceptance criterion at a time.**
5. **Your own run of the verification block on the branch.**

Then open a pending review, add each finding as an inline comment, and submit as
`APPROVE` or `REQUEST_CHANGES`. A review comment is the only way to answer a `BLOCKED:`
or `DECISION REQUIRED:` draft, so make it complete enough to unblock in one round: give
the decision and the reason, not just the verdict. See
[references/REVIEW.md](references/REVIEW.md).

## 5. Review the branch, not just the diff

A pull request can satisfy every one of its own acceptance criteria and still leave the
branch worse. After each merge, and always before closing a wave:

- Run the full verification on the merged branch. Anything the wave claimed to fix must
  be fixed; anything it did not touch must not have regressed.
- Check the wave's collective intent, which no single ticket owns. Ask the question the
  wave was for, not the questions its tickets were for.
- Look for drift no ticket anticipated: a new escape hatch on a public signature, a
  duplicated helper that should have been shared, a docstring that no longer matches
  behaviour, a comment pointing at something outside the repository.

Anything you find becomes a **follow-up issue** - never a silent fix, never an
unrecorded complaint. Name the pull request that introduced it and the acceptance
criterion it undermines. Attach it to the wave epic if it blocks the release, or to a
later wave if it does not.

## Two habits that matter more than they look

**Write the reason down where the work lives.** A decision recorded in your own session
is lost. On the epic, on the pull request, or in the issue body - somewhere an agent or
a human will read it without asking you.

**Say what you did not do.** You are asking every agent for this in their pull requests.
When you re-scope a ticket, stand down from a fix, or defer a finding, hold yourself to
the same standard in the same place.

## When a fix reveals another finding

Closing one defect regularly changes what the other probes can see - a cache that hid a
growth problem, a rejection that masked a leak. After a wave lands, re-run the probes
that were passing, not only the ones that were failing. A finding that quietly starts
reproducing is the most expensive kind to discover late.
