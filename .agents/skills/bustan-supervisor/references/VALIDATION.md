# Validating a ticket before you dispatch anyone

A ticket is a promise about code. Before you spend an agent on it, check the promise
against the exact tree the agent will see.

This takes ten to thirty minutes. A ticket dispatched against a wrong premise costs a
whole agent run, comes back as a draft pull request you then have to answer, and burns a
day of a critical path. The trade is not close.

## The four checks

**1. Does every file in `Owns` exist on the target branch?**

```bash
git worktree add --detach /tmp/probe origin/<target-branch>
for f in <each path from Owns>; do
  [ -e "/tmp/probe/$f" ] && echo "ok      $f" || echo "MISSING $f"
done
```

A missing path is decisive. It means the ticket was written against a different tree and
everything else in it is suspect.

**2. Is the target branch the tree the analysis was done on?**

```bash
git log --oneline <analysis-base>..origin/<target-branch> | wc -l
git diff --stat <analysis-base> origin/<target-branch> -- src | tail -1
```

Any meaningful drift, and every claim in the ticket needs re-checking. A file that has
doubled in length is not drift, it is a different file.

**3. Does the defect actually reproduce there?**

Reading the source is enough to rule a finding *in* as present. It is not enough to rule
it *out*, and it is never enough to size the work. Run a probe.

If the analysis shipped probe scripts, run them - but read their failures rather than
counting them. A probe that dies importing a symbol proves nothing about the defect; it
proves the probe was written elsewhere. Rewrite it against the target tree, or drop the
finding, and say which you did.

**4. Are the acceptance criteria reachable inside `Owns`?**

Take each criterion literally and ask which files satisfying it would touch. A criterion
of the form "this repository-wide check passes" almost always reaches beyond a ticket's
`Owns` set. Either widen `Owns`, or add the exclusion to a file the ticket already owns,
and write that instruction into the ticket so the agent does not have to guess.

## Failure modes that recur

**The analysis was done on the development line and the ticket targets a release tag.**
The most common and the most expensive. Released code and head-of-line code diverge
exactly where active work has been happening, which is exactly where the interesting
findings are.

**One defect masks another.** A caching bug hides a growth bug, because the cache means
the growing thing is only ever built once. A rejection hides a leak, because nothing
gets far enough to leak. When a probe reports the defect absent but the source says it
is present, suspect masking before you drop the finding: change the probe so the masking
path is not taken, and try again.

**The probe exercises the wrong shape.** A probe that injects a type the framework
already rejects proves that rejection, not the finding. Write the probe around the shape
the documentation recommends, because that is the shape users will have written.

**A criterion the ticket cannot satisfy.** Repository-wide format and lint gates, a
generated file compared byte for byte, a coverage floor - all of these reach outside a
narrow `Owns` set.

## Diagnosing a failure on one branch does not diagnose it on another

A red job on two branches is two failures until you have looked at both. Read the **step
conclusions**, not just the job conclusion: a job that fails early skips everything after
it, so two branches can show the same red badge for entirely unrelated reasons, and the
later step you already diagnosed on one branch may never have run on the other.

This costs more than a wasted look. A fix aimed at the wrong step lands, the badge stays
red, and the next person inherits both a broken pipeline and a confident, wrong
explanation of it in the commit log.

Cheapest habit: before generalising any CI diagnosis across branches, fetch the step list
for the specific run on the specific branch you are about to change.

## Writing the result down

Rewrite the ticket from what you found: the verified finding list, a corrected `Owns`,
and the target branch's own verification commands rather than another branch's.

Then post the evidence as a comment on the wave epic, in a table with one row per claim
and a column saying what you actually observed. Include what you dropped and why. That
comment is the reason the release scope is what it is, and it is the only place anyone
will be able to find it later.

## Leave the gate in the agent's tree

If a ticket's acceptance depends on a probe suite, commit the validated suite to the
ticket's base branch before dispatching, so the agent runs the gate in its own working
tree and never has to reach into another branch to be graded. Mark it read-only for the
ticket: an agent that can edit its own gate does not have one.

## A comparison probe must vary only the thing being compared

The point of probing two spellings of one dependency, or two shapes of one composition, is
to show that the framework treats them differently. That only follows if everything else
was held still. A probe where one arm has a parameter default and the other does not, or
where one resolves from a module that can see the token and the other from a module that
cannot, produces a difference that says nothing about the spelling.

Write the arms as one function taking the varying part as an argument, and print the
matrix. If the two arms are separate functions, the difference between them is whatever
you happened to type twice, and a supervisor's table can end up recording a divergence
that runs the other way from the one that exists.

Two corollaries, both learned the expensive way:

- **A refusal is not evidence of the fix you were looking for.** Read what raised it. A
  composition rejected by the route scanner for an unrelated reason is not a composition
  the scope algebra refused, and a shape refused with the hook present says nothing about
  the shape without it.
- **A finding is not closed until the shape the audit actually documented is refused.**
  Run the evidence script. It is the arm you did not write yourself.

## Name a package, not only a module, when a ticket adds tests in a new directory

`Owns` is matched against the paths a pull request touches, and a new test module in a
directory the repository has not used before needs an `__init__.py` beside it. A ticket
that lists `tests/unit/thing/test_thing.py` and nothing else makes its own acceptance
unreachable inside `Owns`: the agent must create a file the ticket forbids. List the
directory.

## Check every acceptance criterion against the Owns list, one by one

The recurring defect in these tickets is not a wrong criterion. It is a criterion that is
right and unreachable: it describes a state of the repository that no edit inside `Owns`
can produce. Three in one wave, all mine:

- "importing the package pulls in nothing else" - unsatisfiable for any subpackage,
  because Python runs the parent's `__init__` first. The agent had to invent a loader
  that sidesteps the package name to make the criterion mean anything.
- "every package has an explicit `__all__`" - while `Owns` listed only the seven
  `__init__.py` files the ticket creates, leaving nine it may not touch.
- "no module outside the adapters imports the web server" - while `core/**`, which holds
  seventeen of those imports, was on the same ticket's **Must not touch** list.

Each cost a round of correspondence and made a good delivery read as a partial one.

Before dispatching, take the acceptance criteria one at a time and name the file each one
would have to change. If that file is not in `Owns`, the ticket is wrong: either widen
`Owns`, move the criterion to a follow-up, or rewrite it to describe what this ticket can
actually make true. Do this last, after both lists are written, because it is a check on
their agreement rather than on either alone.

A criterion that survives this check has a second virtue: it tells the agent where to
work. One that fails it tells the agent to go somewhere it has been forbidden, and the
better the agent, the more time it spends discovering that the instruction contradicts
itself.
