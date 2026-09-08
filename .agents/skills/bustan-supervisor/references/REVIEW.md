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

**`OUTSIDE OWNS` is a question, not a verdict about intent.** What it establishes is that
no grant is visible where grants are supposed to live. It does not establish that nobody
granted it. The maintainer may instruct a delivery session directly, on a channel no
supervisor tool can read, and an agent acting on that instruction is not at fault.

So ask before concluding. Request the change - the file still has to be granted in the
issue body before it can merge - but write the request so that being wrong about the cause
costs a correction rather than an accusation. In particular, never report a channel you
cannot read as one you checked: name the three you can see (reviews, pull request comments,
issue comments) and say the session's own channel is not visible to you. A review that
enumerates four sources and has looked at three is worse than one that looks at three and
says so, because the missing one is where the exculpatory fact lives.

What is always fair to hold an agent to is the record it wrote: a commit message or a
description claiming a grant came from a review, when no review exists, is false whatever
prompted the edit, and correcting it is cheap. Correct the sentence; do not build a verdict
on top of it.

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

## Say a partial grant's refusal as often as you say its grant

A blocked pull request asked for two things. One was safe and was granted; the other named
two files another ticket had open, so it was withheld until that ticket merged. The agent
had already scheduled its own check-in, and that check-in told it to do both the moment a
review arrived. It did not. It took the granted half, waited, and took the second half five
minutes after the release, merging the base branch first as the review asked.

The review is why. It said the deferral three times, in three different registers: a heading
that read "granted, but not yet", a sentence saying which files were in another agent's hands
and that "probably would merge" is what file ownership exists to avoid, and a closing
instruction to wait for a word. A blind agent reconciling a review against its own stale
prompt has only the review's text to weigh, and one mention weighs about as much as the
sentence next to it.

So when a review grants part of what a block asked for, give the withheld part the same
prominence as the granted part - its own heading, its reason, and the condition that lifts
it. A refusal folded into a subordinate clause after two paragraphs of grant is a refusal the
reader has already stopped expecting.

The counter-case is the one that makes this worth writing down rather than filing as luck:
the same agent's self-scheduled check-in was, at that moment, a second instruction telling it
to proceed. Nothing in the harness resolved the conflict. The text did.
