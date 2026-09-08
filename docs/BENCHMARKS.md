# Benchmarks

`Bustan` ships a benchmark suite and a CI job that fails a pull request whose
measurements have drifted past a stated threshold. The suite lives in `benchmarks/`, is
a standalone `uv` project, and is never collected by `pytest` at the repository root.

## What Is Measured

Four benchmarks, each one thing:

| Benchmark | What it measures |
| --- | --- |
| `bench_simple_route` | One `GET` to a default-scoped controller: routing, injection, parameter binding, handler call, response serialization. Nothing else is on the route. |
| `bench_pipeline_route` | The same route with a guard, a parameter pipe and an interceptor on it. The two applications differ in nothing else, so the gap between these two numbers is what the pipeline costs. |
| `bench_request_scoped_chain` | One request to a request-scoped controller over a three-deep chain of request-scoped providers. Nothing on that path is cached between requests, so this is the cost of building a fresh object graph per caller. |
| `bench_container_resolution` | Resolving a transient provider whose dependencies are already built, with no request and no HTTP involved. |

A fifth benchmark, `bench_calibration`, measures a fixed workload that touches no
framework code. It is not a measurement of `Bustan`; it is how run-to-run variation is
divided out. See [What The Ratio Does](#what-the-ratio-does).

Requests are served through the raw ASGI adapter and driven on an event loop the
harness owns. No socket is opened, no HTTP is parsed and no message crosses a thread,
because each of those would otherwise be measured as framework cost. Application
assembly happens once per benchmark, outside the measurement, so what is timed is the
steady state a serving application is in.

Every handler is a coroutine, deliberately. A synchronous handler is dispatched to a
worker thread, and that hand-off costs several times the whole framework path: with
synchronous handlers these benchmarks reported 833 us for a simple route where the
framework's own work is 172 us, so four fifths of the number was the thread pool. What a
synchronous handler costs is worth measuring, but it is a benchmark of its own rather
than a tax on these four.

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

## What The Ratio Does

Every gated number is a ratio: the benchmark's median divided by the median of
`bench_calibration` measured in the same process, in the same run. That absorbs how busy
a runner was and which processor it drew from the fleet - `ubuntu-latest` is not one
machine, and two consecutive runs of this job landed on an EPYC 7763 and an EPYC 9V74.

**It does not make a number portable between machine classes, and that was measured
rather than assumed.** Between the delivery container and a CI runner, on identical code:

| Benchmark | Container (Xeon 2.80GHz) | Runner (EPYC 9V74) | Runner faster by |
| --- | --- | --- | --- |
| `bench_calibration` | 198.1 us | 161.9 us | 18.3% |
| `bench_container_resolution` | 24.1 us | 18.0 us | 25.3% |
| `bench_simple_route` | 172.3 us | 94.5 us | 45.1% |
| `bench_pipeline_route` | 252.8 us | 132.4 us | 47.6% |
| `bench_request_scoped_chain` | 313.8 us | 163.9 us | 47.8% |

The deeper and branchier the call graph, the more a newer processor helps: a tight loop
gains 18%, and the framework's request path gains 45%. No synthetic workload reproduces
that, because it is branch prediction and cache behaviour rather than clock speed. A
calibration workload can therefore cancel the runner, but not the machine class.

That is why the baseline is captured where the gate runs. Judging a run against a
baseline from other hardware judges the hardware, so the gate prints a warning naming
both processors when it sees that, and the verdict on such a comparison is not evidence
of anything.

## The Threshold, And Why It Is 20%

**A benchmark fails the gate when its ratio exceeds the baseline ratio by more than
20%.**

The threshold was chosen from measured spread. These are the eight capture passes the
committed baseline was written from, on the runner:

| Benchmark | Lowest ratio | Highest ratio | Spread | Worst single pass above baseline | Worst best-of-two above baseline |
| --- | --- | --- | --- | --- | --- |
| `bench_simple_route` | 0.5742 | 0.5956 | 3.7% | +1.7% | +1.6% |
| `bench_pipeline_route` | 0.7904 | 0.8374 | 5.9% | +2.6% | +1.4% |
| `bench_request_scoped_chain` | 0.9802 | 1.0463 | 6.7% | +3.4% | +2.0% |
| `bench_container_resolution` | 0.1093 | 0.1133 | 3.7% | +1.4% | +0.4% |

The CI job runs the suite twice and the gate takes the lower ratio each benchmark
reached, so the column that matters is the last one. The worst excursion under that rule
was +2.0%, and 20% is ten times it.

Ten times may look generous against that table, and it is deliberate. The table is eight
passes on one runner instance; the fleet is known to be heterogeneous, and how much a
different processor moves a ratio once the calibration has cancelled what it can has not
yet been measured over enough runs to quote. The margin is for that, and it should come
down as runs accumulate.

What the threshold buys, and what it does not: a change that makes a request 20% slower
is caught, and one that makes it 5% slower is not. A gate that tripped on 5% would trip
on the fleet instead, get muted, and then catch nothing at all.

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

## The CI Job

The `Benchmarks and regression gate` job installs `benchmarks/` on its own, runs the
suite twice, and runs `gate.py` over both result files. It is blocking. The full
comparison table is written to the run summary whether the gate passed or failed,
because the margin a passing run had is what says whether the threshold is still right.
The result files are uploaded as an artifact on every run.

The job is separate from every test job and shares no step with one, so a slow benchmark
never delays the suite.

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
