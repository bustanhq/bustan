# Benchmarks

`Bustan` ships a benchmark suite and a CI job that fails a pull request whose
measurements have drifted past a stated threshold. Beside that gate, the suite times
Bustan against Litestar serving the same requests, and a second CI job holds every route
to a budget of calls into `bustan`. The suite lives in `benchmarks/`, is a standalone
`uv` project, and is never collected by `pytest` at the repository root.

## What Is Measured

The gate judges four benchmarks, each one thing:

| Benchmark | What it measures |
| --- | --- |
| `bench_simple_route` | One `GET` to a default-scoped controller: routing, injection, parameter binding, handler call, response serialization. Nothing else is on the route. |
| `bench_pipeline_route` | The same route with a guard, a parameter pipe and an interceptor on it. The two applications differ in nothing else, so the gap between these two numbers is what the pipeline costs. |
| `bench_request_scoped_chain` | One request to a request-scoped controller over a three-deep chain of request-scoped providers. Nothing on that path is cached between requests, so this is the cost of building a fresh object graph per caller. |
| `bench_container_resolution` | Resolving a transient provider whose dependencies are already built, with no request and no HTTP involved. |

One more, `bench_calibration`, measures a fixed workload that touches no framework code.
It is not a measurement of `Bustan`; it is how run-to-run variation is divided out. See
[What The Ratio Does](../explanation/why-the-benchmark-ratio.md#what-the-ratio-does).

Requests are served through the raw ASGI adapter and driven on an event loop the
harness owns. No socket is opened and no HTTP is parsed, because either would otherwise
be measured as framework cost, and nothing crosses a thread unless the route sends it
there. Application assembly happens once per benchmark, outside the measurement, so what
is timed is the steady state a serving application is in.

Every handler the gate judges is a coroutine, deliberately. A synchronous handler is
dispatched to a worker thread, and that hand-off costs more than the rest of the request
does, so a gated benchmark written that way would mostly time the thread pool. What the
hand-off costs is measured [beside the gate](#beside-the-gate) instead.

## Beside The Gate

Five more benchmarks run in the same suite. The gate prints what they measured and judges
none of them.

| Benchmark | What it measures |
| --- | --- |
| `bench_sync_route` | `bench_simple_route` with its handler written `def` instead of `async def` and nothing else changed, so the gap between the two is the hand-off to a worker thread. |
| `bench_hundred_items_route` | One `GET` answered with a JSON list of a hundred of the simple route's payloads, built once, so what it adds is serializing and sending a larger body. |
| `bench_simple_route_litestar`, `bench_sync_route_litestar`, `bench_hundred_items_route_litestar` | Litestar, at the version `benchmarks/uv.lock` pins, answering the request that the benchmark named without `_litestar` times, with the same bytes. |

Each Litestar twin is written the way Litestar writes it: a controller, the service
provided once and cached, a path parameter declared with `FromPath`, and for the
synchronous route a handler marked `sync_to_thread=True`. It is served by the same
driver, through the same scope and on the same loop as its Bustan counterpart. Its logging
configuration is off, because building a Litestar application with it configures the root
logger for the whole process, and every Bustan benchmark after it would pay for that.

After its verdict the gate prints each pair. From a CI run on a runner with an AMD EPYC
7763:

```text
against Litestar, never judged: the lowest median each reached, in microseconds
benchmark                            bustan   litestar  multiple
bench_hundred_items_route             214.4       81.8     2.62x
bench_simple_route                    185.6       76.3     2.43x
bench_sync_route                      580.7      189.6     3.06x
```

A multiple is of whole requests through the driver, not of the two frameworks' own work.
Every median includes what the driver costs to put one request through its event loop,
the same for both frameworks: on an Apple M4 Pro that is 29.8 us of the simple route's
78.0 us on Bustan and 42.4 us on Litestar, and without it the multiple there would be 3.8
rather than 1.8. The driver's share stays the same whichever framework changes, so a
change in the multiple is a change in one of the frameworks.

Why none of this is gated is in
[Why Litestar Is Printed And Not Judged](../explanation/why-the-benchmark-ratio.md#why-litestar-is-printed-and-not-judged).

### Coroutine And Synchronous Handlers Side By Side

`bench_simple_route` and `bench_sync_route` are one route written both ways. Measure them
together with:

```bash
cd benchmarks
uv sync --frozen
PYTHONHASHSEED=0 uv run pytest bench_simple_route.py bench_sync_route.py
```

Read the median column. The lowest median of two passes of the whole suite, on two
machines:

| Machine | `async def` | `def` | Multiple |
| --- | --- | --- | --- |
| GitHub-hosted runner, AMD EPYC 7763 | 185.6 us | 580.7 us | 3.1 |
| Apple M4 Pro | 78.0 us | 203.8 us | 2.6 |

On both machines a synchronous handler's hand-off costs more than everything else on its
request put together. It is not the framework's own work: the two routes make one call
apart into `bustan` per request, as [the call budget](#the-call-budget) counts them, so the
difference is the worker thread and the scheduling on either side of it. Litestar's twins
show the same shape at a smaller size: its synchronous route costs 2.5 times its coroutine
route on the runner and 2.1 times on the M4 Pro.

What a synchronous handler costs an application, and when it is still the right choice, is
in [Coroutine And Synchronous Handlers](../reference/routing.md#coroutine-and-synchronous-handlers).

### Reproducing The Comparison

The comparison needs nothing but the suite, and it holds on any machine, because both
numbers in a row were measured on that machine:

```bash
cd benchmarks
uv sync --frozen
mkdir -p .benchmark-results
for pass in 1 2; do
  PYTHONHASHSEED=0 uv run pytest --benchmark-json=".benchmark-results/local-$pass.json"
done
uv run python gate.py \
  --result .benchmark-results/local-1.json --result .benchmark-results/local-2.json
```

Anywhere but the runner, the verdict above the comparison judges this machine against the
runner's baseline, says so in a warning, and can exit non-zero; the comparison is
unaffected. The multiples are this machine's, and they differ between machine classes the
way the ratios do: the simple route's was 2.43 on the runner and 1.84 on the M4 Pro.

## Running Them

```bash
cd benchmarks
uv sync --frozen
PYTHONHASHSEED=0 uv run pytest
```

`benchmarks/uv.lock` is this project's own. It depends on the root project by path, so
the root's metadata is recorded in it and a root dependency edit makes it stale exactly
as it makes the six example lockfiles stale. Regenerate it with `uv lock` in
`benchmarks/`; never hand-edit it. CI checks it before installing anything.

`PYTHONHASHSEED` is pinned because dictionary layout follows the hash seed and the
request path is dictionaries. Leaving it unpinned costs several percent of run-to-run
spread. The published baseline records the seed it was captured under, and the gate
prints a warning when a result disagrees with it.

Measurement settings - 1500 rounds, warmup on, garbage collection off - live in
`benchmarks/pyproject.toml` rather than on a command line, because a run under different
settings is not comparable with the baseline and the numbers give no hint that they came
from one.

## The Published Baseline

`benchmarks/baseline.json` is the committed baseline. It is the median across eight
passes **captured on a GitHub-hosted `ubuntu-latest` runner**, which is the machine class
the gate runs on. It records what it was taken on, because a number without that is not a
baseline:

| Field | Value |
| --- | --- |
| CPU | AMD EPYC 9V74 80-Core Processor, 4 cores available |
| Architecture | `x86_64` |
| Operating system | Linux 6.17.0-1022-azure |
| Interpreter | CPython 3.13.15, built with GCC 13.3.0 |
| `PYTHONHASHSEED` | `0` |
| Passes | 8 |

Median wall time per operation, and the ratio the gate actually compares:

| Benchmark | Median | Ratio to calibration |
| --- | --- | --- |
| `bench_simple_route` | 94.5 us | 0.585 |
| `bench_pipeline_route` | 132.4 us | 0.816 |
| `bench_request_scoped_chain` | 163.9 us | 1.012 |
| `bench_container_resolution` | 18.0 us | 0.112 |
| `bench_calibration` | 161.9 us | 1.000 |

Those absolute numbers are published for a reader; the gate never uses them. Read them as
that runner's cost, not as a claim about anyone else's.

## Comparing A Change On Your Own Machine

The committed baseline belongs to CI's hardware, so running the gate against it on a
laptop reports a regression that is not one - the warning it prints says so. To measure
a change locally, compare against yourself:

```bash
cd benchmarks
# On the commit before your change.
for pass in 1 2 3 4; do
  PYTHONHASHSEED=0 uv run pytest --benchmark-json=".benchmark-results/before-$pass.json"
done
uv run python gate.py --write-baseline --output before.json \
  --result .benchmark-results/before-1.json ... --result .benchmark-results/before-4.json

# With your change applied.
for pass in 1 2; do
  PYTHONHASHSEED=0 uv run pytest --benchmark-json=".benchmark-results/after-$pass.json"
done
uv run python gate.py --baseline before.json \
  --result .benchmark-results/after-1.json --result .benchmark-results/after-2.json
```

Same machine on both sides, so the comparison means something. `before.json` is scratch;
do not commit it.

## Moving The Published Baseline

A deliberate change in cost - not a regression, a decision - moves the baseline. There is
one supported way to do it, and it runs on the hardware the gate runs on:

1. Dispatch the `CI` workflow manually on your branch. The `Benchmarks and regression
   gate` job runs its `Capture a baseline on this runner` step only on a dispatch, so a
   normal push does not pay for it.
2. The job prints the new `baseline.json` and the spread table it came from to the run
   summary.
3. Commit that JSON as `benchmarks/baseline.json`, and set its `threshold` from the
   spread table rather than carrying the old number over unexamined.

Eight passes, because one pass is not a baseline. Hand-editing `baseline.json` is not
supported, and neither is capturing it anywhere but the runner.

A capture records only the benchmarks named in `GATED` in `benchmarks/gate.py`. A
benchmark joins the gate by being added there before a capture, and its threshold is then
chosen against the spread that capture prints. None of the benchmarks beside the gate has
been through one.

## The Call Budget

`benchmarks/call_budget.py` serves requests to every Bustan route the suite times and
counts how many of `bustan`'s own functions one request starts. A function is `bustan`'s
when it is written in the package's source, or generated into one of its modules when a
class is created, as a dataclass's `__init__` is. Calls into the application, the standard
library and other dependencies are not counted. Each route serves two requests before
counting starts, because a first request builds what later ones reuse, and the three
requests it then counts must agree.

```bash
cd benchmarks
uv sync --frozen
PYTHONHASHSEED=0 uv run python call_budget.py
```

It prints each route's budget, its count and a verdict - `ok`, `under by N` or
`OVER BY N` - and exits non-zero when any route is over. The budget is
`benchmarks/call_budget.json`, and the `Request call budget` CI job runs the same command.
There is no threshold: a count does not move with the machine, so one call over fails. The
evidence for that is in
[Why The Call Budget Has No Threshold](../explanation/why-the-benchmark-ratio.md#why-the-call-budget-has-no-threshold).

### How The Budget Moves

The budget is written from the tree, never by hand:

```bash
PYTHONHASHSEED=0 uv run python call_budget.py --write
```

- **Down, in the change that removes the calls.** A route under its budget passes and is
  named `under by N`. Writing the budget in the same pull request holds the gain; left at
  the old number, the budget lets a later change spend the calls this one saved without
  failing.
- **Up, only in a change that says why.** A route over its budget fails. When the calls
  are the point of the change - a feature on the request path costs something - write the
  budget and name in the pull request each route that grew, and by how much.
- **With the routes.** A route the script counts that the budget does not name fails, and
  so does a budget entry for a route it no longer counts, so a route added to or removed
  from `ROUTES` in `call_budget.py` is written into the budget in the same change.

## The CI Jobs

The `Benchmarks and regression gate` job installs `benchmarks/` on its own, runs the
suite twice, and runs `gate.py` over both result files. It is blocking. The full
comparison table, and the comparison with Litestar after it, are written to the run
summary whether the gate passed or failed, because the margin a passing run had is what
says whether the threshold is still right. The result files are uploaded as an artifact on
every run.

The `Request call budget` job installs the same project and runs `call_budget.py`. It is
blocking, it times nothing, and it writes its table to the run summary whether it passed
or failed, because a route under its budget is only named there.

Neither job shares a step with a test job, so a slow benchmark never delays the suite.

## Reading A Failure

The gate prints the baseline ratio, the observed ratio and the change for every
benchmark. When one is marked `REGRESSED`:

1. Check for a warning above the table. A processor mismatch means the comparison is
   across machine classes and says nothing about the code.
2. Check whether the change is expected. A new feature on the request path costs
   something, and the honest response is to move the baseline and say so in the pull
   request, not to widen the threshold.
3. Check whether only one benchmark moved. `bench_simple_route` alone points at routing,
   binding or serialization; `bench_pipeline_route` alone points at the pipeline;
   `bench_request_scoped_chain` and `bench_container_resolution` together point at the
   injection kernel.
4. Reproduce it with [the local comparison above](#comparing-a-change-on-your-own-machine).
   The gate is deterministic given the result files, which are attached to the run as an
   artifact.

When `call_budget.py` marks a route `OVER BY N`:

1. Check whether the calls are the point of the change. If they are, move the budget up as
   [described above](#how-the-budget-moves).
2. If they are not, reproduce the count locally with the command above. It is the same on
   any machine, so it is the number CI saw, and running it on each commit of the change
   finds the one that added the calls.

## Where That Material Went

Why the gate compares a ratio, why the threshold is twenty percent, why the comparison with
Litestar is not judged and why the call budget has no threshold are in
[Why The Benchmark Gate Uses A Ratio](../explanation/why-the-benchmark-ratio.md).
