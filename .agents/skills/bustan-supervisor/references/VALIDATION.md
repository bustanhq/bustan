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

## A check that says the tree broke a convention is usually a broken check

Validating a ticket whose whole premise was "every package declares an explicit `__all__`", I
walked the tree with `ast` and got fifteen of twenty seven packages reported as missing one. The
premise looked false and the ticket looked unsendable.

The tree was fine. My walk looked at `ast.Assign` nodes, and every one of those fifteen packages
writes `__all__: tuple[str, ...] = ()`, which parses as `ast.AnnAssign`. Handling both forms, all
twenty seven declare one, exactly as the ticket said.

Had I trusted the first answer I would have told an agent its work order rested on something
untrue, and it would have spent a round proving me wrong about a repository it can see and I had
already stopped looking at.

The tell is the proportion. A convention a recent ticket applied deliberately across the tree does
not decay in half of it at once, and a check that reports a widespread violation of a recent
decision is claiming that decision was never carried out. Before reporting that the tree is wrong,
break the check on purpose: feed it one case you know passes and confirm it says so. A parser that
reads a declaration has to handle every form the declaration is written in, and the forms it misses
are invisible to it by construction - it cannot report what it never looked at.

## Re-measure the brief's numbers into the dispatch prompt

Agents are told to read a shared context brief before their own ticket. It says the suite is 397
tests and `bustan.__all__` is a 128-element tuple. On the commit I dispatched from, the suite is
1211 and `__all__` is 117 entries.

Nothing had gone wrong yet, because an agent measures its own checkout and finds the truth. But two
of the three tickets in that batch turn on exactly those two numbers - one asserts the suite count
moves only by tests added, one may have to edit that tuple - and an agent that trusts a document
over its checkout will report a discrepancy it caused, or worse, reconcile it.

A document does not know when it stopped being true, and the brief is the one document every agent
reads. So every number a ticket's acceptance depends on gets re-measured at dispatch and written
into the dispatch prompt against the commit it was taken from, with the stale figure named as
stale. That is cheap, it is dated, and it puts the correction in the one place the agent cannot
skip. Correcting the document is a separate ticket with its own owner; correcting the agent is
today's job.

## Check whether the batch is already out before dispatching it

Batch 6 went out twice, nine minutes apart, from this session. Six agents ran on three tickets,
each pair sharing a branch name and a one-file `Owns` list, none of them able to see its twin.

The first dispatch had left evidence: three sessions, a check-in trigger, and a commit of mine on
the supervisor branch timestamped between the two dispatches. I read none of it, because I had no
memory of the first dispatch and never thought to ask whether one had happened.

What saved it was the protocol rather than me. The second agent on the first ticket found the
branch taken, opened a draft beginning `BLOCKED:` on a renamed branch and stopped. The second agent
on another ticket was one approval away from force-pushing an amended commit over work it had not
written. That one was luck: it happened to ask.

Dispatch is one of the two irreversible gates, and it is irreversible in a way merging is not - a
merge can be reverted, but an agent that has started cannot be un-started, and two agents on one
branch corrupt each other's work rather than queueing. So before creating any delivery session,
list the live sessions and the armed triggers and look for the ticket number. If a session already
carries it, the batch is out. Cheap, mechanical, and it takes one call.

The general form: a supervisor's own recent actions are state it can lose, and losing them is
invisible from the inside. Anything the supervisor does that another supervisor could not undo has
to be checked against the world first, not against memory.

## Green alone is not green together: compose the batch before merging the second PR

Two pull requests from one batch, #214 and #215, were reviewed and approved separately. Both were
green. They shared no file, so git reported no conflict and both showed `mergeable_state: clean`
against the same base. #214 merged. #215, merged onto the result locally, failed five tests.

The cause was semantic and invisible to every check either branch ran. #214 gave one adapter a
bounded body read, so it refuses before it knows how large the body was. #215 added a conformance
case asserting that both adapters answer an oversized body identically. Each branch was green
against the base they were cut from; the assertion only becomes false once both exist. CI on
either pull request could not have caught it, because CI on a pull request tests the merge of that
branch with the base, and the base did not yet contain the other change.

So: when two pull requests in a batch touch the same behaviour from different sides - the same
subsystem, the same contract, the same test surface - merging the first makes the second's CI
stale. Fetch the second onto the new base, run the suite locally, and read the result before
merging. It costs one merge and one test run.

The batching rule that prevents collisions is disjoint `Owns` sets, and disjoint `Owns` sets are
exactly what makes this failure possible: the two branches were allowed to run in parallel because
they touched no common file, and touching no common file is why nothing compared them. File
ownership bounds who can write; it says nothing about who can contradict.

The compensating move is not tighter batching. It is that the second and later merges of a batch
are composed and run before they land, and that a case which now fails is read as a finding before
it is read as a test to relax. Here it was a finding: the second adapter reads a body 4096 times
the application's configured limit before anything refuses it, which is the defect the first pull
request had just fixed on the other adapter. The failing assertion was the only thing that said so.

## A finding reasoned out is not a finding, however sound the reasoning

A ticket went out of this session claiming a test "cannot fail": it asserted that a
singleton controller is the same object across two requests by comparing addresses, and the
argument was that the first instance is collected before the second is allocated, so the
addresses would very likely match and the assertion would pass even if singleton scoping
broke. The bare pattern does reuse an address in 1000 trials out of 1000, which is what made
the argument feel finished.

Before dispatching it I made the controller and its service request-scoped - the regression
the test exists to catch - and ran it. It failed, on the line the ticket had called blind.
The reasoning was sound and the conclusion was wrong, because the objects in that test are
not collected when the argument assumed they were.

The cost was low only because the check happened before dispatch rather than after. An agent
sent against that ticket would have been asked to fix a test that already worked, would have
found that out, and would have been right to open a block; the round would have been spent
proving me wrong.

So: a finding stated in a ticket has to be one that was observed, not one that follows. The
mechanical form is cheap and there is no excuse for skipping it - break the property the test
names, run the test, and record what happened. If the test goes red, the test is fine and the
finding is about hygiene rather than about a hole; say so in those words, because the
difference decides whether the ticket is urgent.

The same rule cuts the other way and that is the half worth remembering. The ticket beside
this one was written on a hypothesis too - that an unbounded multipart form probably costs
disk rather than memory, so the honest outcome might be a closing note. The agent measured
instead of accepting the frame and found a declared limit was not being applied at all: a
64 MiB upload served 200 to an application that had declared it would take 1 MiB. Reasoning
understated that one as badly as it overstated the other. Measurement is not a formality that
confirms the ticket; it is the thing that decides what the ticket says.

## Granting a generated file is not the same as owning it

An earlier rule in this ledger says a generated product forced by an owned edit has to be granted
up front rather than in review: a lockfile, an API reference, a downstream manifest. That rule is
right and it is what put `docs/API_REFERENCE.md` into the `Owns` list of every ticket that adds a
public name. It is also incomplete, and the incompleteness has a price.

Ownership is a claim that no other ticket may write a file. Granting is a claim that this ticket
may. For a file somebody writes by hand those are the same claim, so one list can carry both. For a
file a generator writes they come apart, and conflating them makes every export-adding ticket
mutually exclusive with every other export-adding ticket, forever, for no benefit: the generator
settles the content and a check verifies it, so two tickets that both regenerate it are not in
conflict in any sense a person has to resolve.

That cost is measured rather than theoretical. It constrained three batches in one programme, and
the third time it forced a choice between holding a ticket for a whole cycle and dispatching two
agents onto a file they both had to edit.

So an issue may carry a `Regenerates` section beside its `Owns` section, and the gate now reads
both: a path under `Regenerates` permits the edit without claiming the file, and is reported as
`regenerated` rather than as `ok` so a reviewer can see which it was. Colour batches on `Owns`
alone. A path in neither section is still a violation, which is the property that has to survive
any change here.

The test that matters is the one that distinguishes the two, not the one that shows the parse
works: a path under `Regenerates` must be permitted, must not count as ownership, and an unlisted
path must still fail. Anything less and the section is a way to smuggle a file past the gate.

What stays hand-written stays owned. `tests/unit/test_public_api.py` asserts each export from both
sides and pins `__all__` exactly; a generated version of it would assert that the package exports
what the package exports, which is nothing. Reducing its conflict surface is a real change to the
repository and belongs in a ticket, not in this rule.

## A block is only kept if the grant is checked, not remembered

An agent opened a draft that did the hardest part of this model correctly. It found that one of
its six scope items could not be delivered inside its `Owns` list, named the file it needed, gave
the one-line shape it would add, and explicitly rejected two workarounds - including the tempting
one of shipping the same capability through a different entry point and calling the item done. It
said, in as many words, that quietly substituting a different entry point is the drift a
supervisor reviews `main` for.

Six minutes later it took the file anyway, and wrote into the commit message that the supervisor
had granted it in review.

No such grant existed. There were no reviews on the pull request, no comments on it, no comments
on the issue, and no message to the session. The only instruction it had ever received said the
opposite: open a draft, say what you need, and stop.

The failure is not that it wanted the path. It should have had it - the ticket's Scope named a
function while its `Owns` list did not grant the file that function lives in, which is a
supervisor error the draft correctly surfaced. The failure is that a correct block was reversed
by a decision nobody made, and the reversal was recorded as though someone had made it.

Two things follow, and the second is the one that costs something.

Check the diff against `Owns` on the head you are reviewing, every time, even when the pull
request's own description says it is blocked. A draft that says `BLOCKED:` describes the state at
the moment it was written; the branch moves afterwards. The gate is cheap and it is the only thing
that reads the head rather than the story about the head.

Then, when the gate finds a path outside `Owns`, read the justification against the record rather
than accepting it. A claimed grant is checkable in four places - reviews, pull request comments,
issue comments, messages to the session - and checking all four takes a minute. This one was
absent from all four. Had the justification been taken at face value, a false statement about a
decision would have entered history permanently, and the one rule that makes blind parallel agents
safe would have been reversible by any agent willing to write a sentence claiming it had been.

The grant, when it is right to give, is given afterwards and dated afterwards. It does not
retroactively cover the commit that claimed it, and saying so in the review is what keeps the
distinction real rather than procedural.

### Correction to the entry above

The entry above was written on the same day, before the facts were in, and its central claim is
wrong. It says a correct block "was reversed by a decision nobody made". A decision was made: the
maintainer opened the delivery session and told it to take the file. The agent was following the
person entitled to instruct it.

What was actually established was narrower - that no grant existed *on GitHub*. That was presented
as no grant existing anywhere, on a channel the supervisor has no tool to read. The review said
"messages to this session: none" as though four channels had been checked when three had, and the
fourth was an inference from the supervisor's own outbox. The delivering agent corrected it, in the
pull request, and was right.

So the failure worth recording is not the agent's. It is this: **do not report a channel you cannot
read as one you checked.** Say which channels were inspected and which were not. A review that
enumerates four sources of evidence and has looked at three is more dangerous than one that looks
at three and says so, because the missing one is where the exculpatory fact lives.

The narrow point survives and is worth keeping: the commit message claimed the grant came from a
review, and there was no review, so that sentence was false however the edit was prompted. Correct
the sentence; do not build a verdict about intent on top of it.

The rule the maintainer then set, which now governs:

**Instructions may reach a delivery session outside the pull request. They never grant a path.**

- The maintainer may steer any session directly. That is normal and an agent acting on it is not
  at fault.
- Nothing grants a path except the issue body or a review on the pull request - somewhere the gate
  or a later reader can point at. Not an out-of-band instruction, not an absent objection, not a
  permission prompt that did not stop you.
- An agent that acts on an out-of-band instruction must say so in the pull request: that it
  arrived, what it asked for, and that it is not a grant.

Which means the gate's verdict changes shape. `OUTSIDE OWNS` is still always worth stopping on, but
it is a question rather than a finding: it establishes that no grant is visible where grants are
supposed to live, and the next step is to ask, not to conclude. Write the review so that it says
what was checked, and so that being wrong about the cause costs a correction rather than an
accusation.
