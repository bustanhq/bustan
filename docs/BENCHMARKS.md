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
framework code. It is not a measurement of `Bustan`; it is how the machine is divided
out. See [Why The Gate Compares Ratios](#why-the-gate-compares-ratios).

Requests are served through the raw ASGI adapter and driven on an event loop the
harness owns. No socket is opened, no HTTP is parsed and no message crosses a thread,
because each of those would otherwise be measured as framework cost. Application
assembly happens once per benchmark, outside the measurement, so what is timed is the
steady state a serving application is in.

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
passes, and it records the machine and interpreter it was taken on, because a number
without those is not a baseline:

| Field | Value |
| --- | --- |
| CPU | Intel(R) Xeon(R) Processor @ 2.80GHz, 4 cores |
| Architecture | `x86_64` |
| Operating system | Linux 6.18.44-fc-v24 |
| Interpreter | CPython 3.13.12, built with GCC 13.3.0 |
| `PYTHONHASHSEED` | `0` |
| Passes | 8 |

Median wall time per operation on that machine:

| Benchmark | Median | Ratio to calibration |
| --- | --- | --- |
| `bench_simple_route` | 833 us | 0.968 |
| `bench_pipeline_route` | 912 us | 1.072 |
| `bench_request_scoped_chain` | 977 us | 1.160 |
| `bench_container_resolution` | 24.0 us | 0.028 |
| `bench_calibration` | 848 us | 1.000 |

Those absolute numbers are published for a reader; the gate never uses them. Read them
as this machine's cost, not as a claim about anyone else's.

## Why The Gate Compares Ratios

A CI runner is not a machine. The same job lands on hardware whose absolute speed varies
by more than any regression worth catching, and the baseline above was captured on a
machine that is not a GitHub runner at all. An absolute-time gate would therefore be
measuring the runner.

So every gated number is a ratio: the benchmark's median divided by the median of
`bench_calibration` measured in the same process on the same runner. The calibration
workload is a deliberate mix of what the request path spends its time on - calls,
attribute reads on a slotted object, dict construction, string formatting, JSON
serialization and awaiting on an event loop - and it is sized so that one run of it
costs roughly what one simple request costs. Sizing it that way keeps the same relative
resolution on both sides of the division, so the ratio is no noisier than its worse half.

## The Threshold, And Why It Is 30%

**A benchmark fails the gate when its ratio exceeds the baseline ratio by more than
30%.**

The threshold was chosen from measured spread rather than picked. Across the eight
baseline capture passes on one otherwise idle machine:

| Benchmark | Lowest ratio | Highest ratio | Spread | Worst single pass above baseline | Worst best-of-two above baseline |
| --- | --- | --- | --- | --- | --- |
| `bench_simple_route` | 0.9467 | 1.0251 | 8.3% | +5.9% | +4.0% |
| `bench_pipeline_route` | 1.0067 | 1.1785 | 17.1% | +10.0% | +6.5% |
| `bench_request_scoped_chain` | 1.1165 | 1.2010 | 7.6% | +3.5% | +3.1% |
| `bench_container_resolution` | 0.0271 | 0.0290 | 6.8% | +2.2% | +0.9% |

The CI job runs the suite twice and the gate takes the lower ratio each benchmark
reached, so the column that matters is the last one. The worst excursion above baseline
under that rule was +6.5%. A 30% threshold is four and a half times that, which is the
margin the gate is asking for against a runner noisier than the machine those passes
came from.

What the threshold buys, and what it does not: a change that makes a request 30% slower
is caught, and one that makes it 10% slower is not. A gate that tripped on 10% would
trip on noise instead, get muted, and then catch nothing at all.

## Moving The Baseline

A deliberate change in cost - not a regression, a decision - moves the baseline. There
is one supported way to do it:

```bash
cd benchmarks
for pass in 1 2 3 4 5 6 7 8; do
  PYTHONHASHSEED=0 uv run pytest --benchmark-json=".benchmark-results/pass-$pass.json"
done
uv run python gate.py --write-baseline \
  --result .benchmark-results/pass-1.json \
  ... \
  --result .benchmark-results/pass-8.json
```

Eight passes, because one pass is not a baseline. The new file records the machine it
was captured on, so a reviewer can see when a baseline moved because the hardware
changed rather than because the framework did.

Hand-editing `baseline.json` is not supported. Neither is capturing it on a CI runner:
the whole point of the ratio is that the capture machine does not have to be the gate
machine, and a baseline captured under a noisy neighbour would bake that neighbour in.

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

1. Check whether the change is expected. A new feature on the request path costs
   something, and the honest response is to move the baseline and say so in the pull
   request, not to widen the threshold.
2. Check whether only one benchmark moved. `bench_simple_route` alone points at routing,
   binding or serialization; `bench_pipeline_route` alone points at the pipeline;
   `bench_request_scoped_chain` and `bench_container_resolution` together point at the
   injection kernel.
3. Reproduce it locally with the command in [Running Them](#running-them). The gate is
   deterministic given the result files, which are attached to the run as an artifact.
