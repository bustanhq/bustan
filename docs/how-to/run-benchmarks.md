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
divided out. See [What The Ratio Does](../explanation/why-the-benchmark-ratio.md#what-the-ratio-does).

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

## Where That Material Went

Why the gate compares a ratio, and why the threshold is twenty percent, are in [Why The Benchmark Gate Uses A Ratio](../explanation/why-the-benchmark-ratio.md).
