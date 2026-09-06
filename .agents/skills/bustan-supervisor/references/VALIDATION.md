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

## Keep an Owns section to paths, and put every explanation behind a bold lead-in

The ownership gate reads from the `Owns` heading to the first bold lead-in, markdown
heading or rule, and pulls every backticked run out of everything in between. So prose
inside the section is not ignored - it is parsed. A sentence explaining which test
function changes contributes that function's name as a candidate path, and the gate
refuses the whole list rather than guess.

That refusal is correct and should not be worked around with `--owns`. Fix the ticket:

- The `Owns` section is a bullet list of literal repository paths, one per line, and
  nothing else. No trailing prose after an em-dash, no line numbers, no method names.
- Everything a reader needs about those paths goes underneath, behind a bold lead-in of
  its own - `**Notes on that list.**` works and terminates the section cleanly.
- A path the ticket will create is still a path. Write it out.

Two lists in one wave failed this: one named three test functions in trailing prose, and
one said "the nine `__init__.py` files listed above", which is a cross-reference the gate
cannot follow. Both parsed only after the prose moved behind a lead-in.

Verify by running the parser rather than by reading. Every pattern should resolve to at
least one existing file, or be a path the ticket is explicitly creating. A pattern that
matches nothing and creates nothing is a typo the gate will not catch for you, because a
pattern matching no file also flags no file as unowned.

## Grep the whole suite for the string a ticket changes, not only the modules it edits

Checking each acceptance criterion against `Owns` catches a criterion with no legal home.
It does not catch the other half of the same problem: a criterion whose home is correct, and
which is nonetheless unreachable because a test somewhere else asserts the behaviour being
removed.

A security ticket asked that a 403 stop naming the guard's class path. Its `Owns` listed the
two modules that build the message and the two unit-test files covering them, and every
criterion had a file it could be satisfied in. The agent implemented it correctly and then
opened a `BLOCKED:` draft, because two integration tests it did not own asserted the exact
string the ticket exists to delete:

```
tests/integration/pipeline/test_request_pipeline.py
    assert response.json()["detail"].endswith("DenyGuard blocked the request")
tests/integration/security/test_policy_plan.py
    assert response.json()["detail"] == "Policy denied: missing roles ('admin',)"
```

Both were right to block on. Neither was visible from reading the ticket's own modules,
because a test that asserts an observable response does not have to live near the code that
produces it.

So when a ticket changes something a caller can see - a status, a header, a message, a
payload shape - grep the entire **repository** for the current wording before writing `Owns`,
and add every file that asserts or teaches it. Not the test tree, and not a list of
directories: `git grep` from the root, with no path argument at all.

That distinction cost a second round on the very next ticket. A ticket retiring a documented
testing pattern had its `Owns` widened after a sweep of `docs/`, `src/`, `tests/` and
`examples/` - which found two guides and a whole example project, and missed the
repository-root `README.md`, where the same recipe was taught to every first-time reader. The
agent delivered correctly, the criterion "no documentation still shows the retired pattern"
was still unmet, and the file had to be granted a second time. A directory list is a guess
about where the repository keeps things; the root is not a directory anyone remembers to name. The grep is the check; reading the modules the ticket edits
is not a substitute, and neither is running the suite, which passes right up until the fix
exists.

A test asserting the behaviour a ticket removes is a test defending the defect. Granting it
is correct, and the grant is bounded: name the file, and say that changing the assertion is
in scope while changing anything else in it is not.

## A grant the gate cannot see is not a grant

Write every grant into the ticket's `Owns` bullet list, not only into the prose that explains
it. The ownership gate parses the list and stops at the first bold lead-in that follows, so an
amendment written below that point - however clearly it names the file and however carefully it
bounds the grant - is invisible to the check that decides whether a pull request stays inside
its lane.

This was caught by running the gate rather than by reading the amendment. A ticket was granted
a source file in an amendment paragraph, the gate was run against the draft to confirm the new
boundary, and the parsed-patterns line it always prints did not contain the file:

```
ownership patterns (issue #82): ... tests/integration/core/test_request_boundary.py,
docs/API_REFERENCE.md, uv run python scripts/generate_api_reference.py
```

Had the agent gone on to edit the granted file, the gate would have reported it as outside the
ticket's ownership and the reviewer would have had to decide, at merge time, whether the
refusal was real or an artefact of where the grant was typed. That is the one thing a gate
must never make a reviewer do.

Two consequences. Amend the bullet list first and let the prose explain the bound afterwards.
And read the parsed-patterns line every time, which is why the gate prints it: the same output
shows this ticket parsing a backticked command out of a bullet as though it were a path, which
is harmless only because no changed file will ever match it.

## Disjoint files do not make two tickets independent

Ownership keeps two agents from writing the same line. It says nothing about one ticket
introducing a rule the other ticket's tests break. Two tickets can own entirely disjoint files,
each be green on its own branch, pass every check in CI, and still fail the moment both are on
one tree.

That happened between a ticket that made resolving after a completed shutdown a refusal and a
ticket that made one token answer with one type. Their file sets do not intersect anywhere. The
first merged; the second, whose own branch was green at 1142 passing, then failed one of its own
new tests:

```
ProviderResolutionError: ApplicationProbe cannot be resolved because the application has
been shut down and every instance it built has been destroyed
```

The test took its second reading after the `with TestClient(...)` block, which is legal until
the other ticket exists and illegal afterwards. Neither agent could have seen it: each was
blind to the other by design, and the rule only exists on the merged tree.

So the check is not on either branch. Before merging the second of two tickets that landed in
the same wave, merge the new `main` into it in a scratch worktree and run the suite there. A
green pull request means green against the `main` it was cut from. Only the composed tree
answers the question the merge actually asks.

Two smaller notes from the same episode. The failure was in the second ticket's own file, so
sending it back cost one round and no grant - which is the outcome to aim for, and an argument
for letting the agent fix it rather than reaching into its lane. And the shape recurs: a probe
or assertion taken outside the lifespan it is about is wrong twice over, once as a reading of
a shut-down application and once as a test that will break when somebody makes that a refusal.
Look for it in any ticket that adds a lifecycle rule.

## Verify the reason, not only the conclusion

A ticket that reaches the right conclusion from the wrong reason still sends the agent to argue
the wrong case, and the agent cannot check the reasoning because it only has the ticket.

One filed here said a helper could not be imported across two packages because one sits below
the other in the layering. The conclusion was right and the reason was invented. The layer table
in `scripts/check_layering.py` puts both packages in a single layer, so an import between them
breaks no layering rule at all. What actually forbids it is a module-level import cycle, which
the interpreter states plainly the moment you try:

```
ImportError: cannot import name 'token_identity' from partially initialized module
```

The difference is not academic. The wrong reason pointed at a fix that would have made the
layering worse to no purpose; the real reason points at the fix that removes the cycle, which is
the opposite recommendation. Had the ticket been dispatched as filed, the agent would have
written a draft arguing a case the repository does not support.

So when a ticket asserts that something cannot be done, do the thing in a scratch tree and read
the error before writing the ticket. An architecture rule stated in a document or a layer table
is a description of intent; the import graph is the fact. The same holds for any constraint a
ticket hands an agent as given: a claimed refusal, an ordering, a file said to be untouchable.
Try it, and quote what came back.

## A ticket whose verification block reaches outside its Owns cannot be delivered

Read the verification block against the `Owns` list before dispatch, and ask what each command
touches. A step that exercises files the ticket may not edit is not a strict instruction - it is
a contradiction, and the agent meets it by breaking one half or the other.

One shipped that way. A ticket moved a dependency behind an optional extra, forbade
`examples/**`, and required `run_examples.py` to pass. Every example imported that dependency
and got it transitively, so the move broke all six: the block could not pass while the list held.
No correct delivery existed. The agent edited the twelve files, put them in a table at the top of
the pull request with the reason for each, and offered to lift them out - which is the only way
the contradiction could have surfaced. A delivery that had edited them quietly, or blocked, would
have hidden it.

The check is quick and mechanical. For each command in the block, name the files it reads and the
files it can fail on, and confirm the ticket may edit every one it can be required to fix.
Generated products count: a lockfile regenerated from an owned manifest, an API reference
regenerated from an owned docstring, and a downstream project's manifest that must follow a
dependency change are all forced by an owned edit, and all of them need granting up front rather
than in review.

Two smaller notes from the same episode, both about amending the list rather than the rule.

Anchor an `Owns` amendment on the `## Owns` heading, never on a path string. A path that appears
in the acceptance criteria as well as the list will take the edit into the wrong section, where
the gate cannot see it, and the ticket reads as amended while the gate still refuses. That has
now happened three times in one programme: once by writing a grant only in prose, once by
striking a path through while leaving its backticks, and once by anchoring on a duplicated path.

And run the gate after every amendment, against any pull request, purely to read back the parsed
pattern line. All three of those were caught that way and none was visible in the rendered issue.

## A prohibition states a fact, so grep it before writing it

An `Owns` grant gets checked because the gate checks it. The `Must not touch` list gets no such
check, and neither does an acceptance criterion, so both are where an unverified belief survives
all the way to a delivering agent.

The layout move forbade an entire directory on the stated reason that "the repro scripts import
from `bustan` by its public names and must keep working untouched, which is itself a check that
the public surface did not move". Seventeen of the nineteen executed scripts do. Two import
`bustan.core.ioc.registry`, an internal path. One grep of the directory would have found them.
Instead the ticket forbade the only edit that could complete it, and the agent had no correct
delivery available: it did the whole move, verified it, and opened a draft blocked on three lines.

The same ticket carried an acceptance criterion reading "`tests/unit/test_public_api.py` passes
**untouched**. If it needs an edit, the move changed the public surface and something is wrong."
That is a claim about the contents of one named file, and it is false: the file imports internal
symbols by module path precisely so it can assert the public re-exports are the same objects, so a
package rename must rewrite those lines and says nothing at all about the public surface. The
agent read the file, judged the criterion wrong rather than the move, and said so with a one-line
command as evidence. It was right.

So: every clause that names a path and asserts something about what is inside it - a prohibition's
reason, an acceptance criterion, a "this must not change" - is a factual claim, and gets verified
the same way a grant does, by reading the file. If the reason cannot be checked cheaply, do not
write the reason; write the prohibition alone. A prohibition with no stated reason is honest. A
prohibition resting on a false one is a ticket that cannot be delivered, and the agent pays for it
with a full round.

The tell is grammatical. Any prohibition whose sentence contains "because", "since", "as", or a
dash followed by an explanation is asserting something checkable. Check it.
