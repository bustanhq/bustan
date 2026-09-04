# Reviewing a delivery pull request

Cheap mechanical gates first. Never read logic in a pull request that a later gate is
going to reject anyway.

## 1. Ownership

```bash
scripts/check_ownership.py --repo OWNER/REPO --pr N --owns-from-issue M
```

Any file outside `Owns` is `REQUEST_CHANGES`, regardless of the quality of the change.
Say which file and quote the ticket's `Owns` list back, so the agent can see the rule
rather than infer a preference.

The script prints the patterns it parsed. Read that line. If it parsed the wrong thing,
pass the patterns explicitly with repeated `--owns` flags instead of trusting the parse.

**An amendment to `Owns` belongs in the issue body, never only in a comment.** Granting a
file in a review comment is invisible to the gate, which reads the body, so the next run
reports the granted file as a violation and the reviewer has no reason to doubt it. It is
also invisible to an agent that read the issue before the comment existed. Edit the body,
then say in the comment that you did.

## 1b. When a ticket edits the acceptance gate

Normally an edit to the probes that grade a ticket is the clearest possible `REQUEST_CHANGES`:
a ticket that adjusts the thing measuring it has stopped being measured.

**But a fix can make a probe's own setup illegal.** A probe that builds a graph the framework
now refuses cannot observe its own fix - left alone it raises before reaching its verdict and
reports `ERROR` forever, which fails the shared verification block for every ticket after it.
That edit is necessary, and forbidding it outright pushes an honest agent into either shipping
a red gate or arguing the point in a pull request.

Tell them the difference in the ticket: adapt the plumbing so the probe can still reach its
verdict, never the condition it grades. Then check it rather than believing it.

**The check that settles it: run the edited probe against the branch the defect still lives
on.** A probe edited to pass will pass there too; a probe edited to survive a legal change
still reports the defect. That one run distinguishes an adaptation from a laundering, and it
takes a minute.

Two supporting signals, neither sufficient alone: a probe whose finding **still reproduces**
after being edited is strong evidence of good faith, since gaming would have flipped it; and a
probe whose edit changes the *shape* of what it constructs, rather than only its plumbing,
deserves more scrutiny than one that moves a line into a `try`.

## 2. Continuous integration

Red means not reviewed. Say so and stop; do not spend a review round on code whose own
checks reject it.

## 3. The pull request contract

Every element, in order: ticket id and title; findings closed; a prose summary a
reviewer can read without opening the diff; which probes moved from failing to passing;
the verification output pasted verbatim; every decision where the ticket left more than
one defensible option, each with its reason; and everything the agent deliberately did
not do.

The last one is not a formality. A silent omission and an oversight look identical to a
reviewer who cannot ask a question. A pull request missing it goes back unread.

## 4. The diff against the acceptance criteria

One criterion at a time, in the ticket's order. Read for whether the criterion is met,
not for whether the code is what you would have written.

Two things always worth checking, because they are how a passing ticket still damages
the branch:

- **A public symbol whose documented behaviour changed** without the change being
  declared.
- **A comment or docstring that no longer matches the code beside it.** Those become
  the next contributor's mental model.

## 5. Your own run

Run the verification block on the branch yourself. The agent's paste proves it ran; your
run proves it passes. This catches the case where a check passes only in the agent's
container.

## Submitting

Open a pending review, attach each finding as an inline comment on the line it concerns,
then submit as `APPROVE` or `REQUEST_CHANGES`.

**When the agents run under your own account, GitHub refuses both verdicts** - it will not
let an account approve or request changes on its own pull request. Submit the review as a
`COMMENT` instead and say in the first line which verdict it carries, so the record is
unambiguous for anyone reading the thread later. Do not let the tooling limitation soften
the verdict into a suggestion.

## Before you merge, check the issue actually closes

`Closes #N` inside backticks is a code span, and GitHub does not parse closing keywords
inside one. A pull request whose description reads ``Closes #12`` in code formatting will
merge and leave its issue open, which silently breaks the wave epic's progress bar and the
milestone burndown you are using to decide when the wave is done.

A closing keyword also only fires for a pull request merged into the repository's
**default** branch. Work on a maintenance or release branch never closes its issue
automatically however the description is written, so those always need closing by hand.

Check the issue's state after every merge, and close it by hand when the link did not
fire. Better, catch it at review time: the contract says the description must contain a
working `Closes #N`, and a formatted one does not qualify.

## Answering a blocked or decision-required draft

A review comment is your only channel. Make it complete enough to unblock in one round:

- State the decision, not the verdict. "Use the second option" without the reason leaves
  the agent unable to apply the same judgement to the next case.
- Answer everything the draft raised, including the parts you think are obvious.
- If the draft found that the ticket contradicts the code, the agent is probably right
  and the ticket is probably wrong. Fix the ticket, say you fixed it, and say what
  changed.

## What is worth a follow-up rather than a change request

Ask whether the finding is inside the ticket's scope. If it is not, requesting changes
makes the agent widen a pull request beyond what it was given, which is the thing you
spend the rest of your time preventing.

Merge the pull request that meets its criteria, and file the rest as a follow-up naming
the pull request that introduced it and the criterion it undermines.
