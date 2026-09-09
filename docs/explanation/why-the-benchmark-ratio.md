# Why The Benchmark Gate Uses A Ratio

The benchmark gate compares a ratio rather than a wall-clock number, and refuses a change at twenty percent rather than at some tighter figure. Both choices are deliberate and neither is obvious.

For running the benchmarks and reading a failure, see [Run The Benchmarks](../how-to/run-benchmarks.md).

## What The Ratio Does

Every gated number is a ratio: the benchmark's median divided by the median of
`bench_calibration` measured in the same process, in the same run. That absorbs how busy
a runner was and which processor it drew from the fleet - `ubuntu-latest` is not one
machine, and two consecutive runs of this job landed on an EPYC 7763 and an EPYC 9V74.

**That it works within the fleet has been measured.** The run that gated this benchmark
suite drew a different runner VM from the one the baseline was captured on, same processor
model. In absolute terms the two runs disagreed by 21% - the calibration workload measured
161.9 us on the capture and 195.1 us on the gate run - and after dividing that out, every
gated ratio landed within 3.3% of its baseline:

| Benchmark | Baseline ratio | Gate run ratio | Difference |
| --- | --- | --- | --- |
| `bench_simple_route` | 0.5854 | 0.6013 | +2.7% |
| `bench_pipeline_route` | 0.8164 | 0.8396 | +2.8% |
| `bench_request_scoped_chain` | 1.0118 | 1.0448 | +3.3% |
| `bench_container_resolution` | 0.1118 | 0.1145 | +2.4% |

A 21% swing in what the machine cost, reduced to 3% in what the gate reads, is the whole
reason the ratio is there.

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

Ten times may look generous against that table, and it is deliberate. Those eight passes
share one runner VM, so they measure less than a real gate run faces. The first
independent run - a different VM, a 21% swing in absolute cost - came in at +3.3%, which
is the number to weigh, and 20% is six times it. Two data points is still not a
distribution, and the fleet mixes processor models: the two capture runs on this branch
drew an EPYC 7763 and an EPYC 9V74. The margin covers what has not been seen yet, and it
should come down as runs accumulate.

What the threshold buys, and what it does not: a change that makes a request 20% slower
is caught, and one that makes it 5% slower is not. A gate that tripped on 5% would trip
on the fleet instead, get muted, and then catch nothing at all.
