# Benchmarks

A standalone `uv` project holding the framework's benchmark suite and the regression
gate that CI runs over it. It is not collected by `pytest` at the repository root and
its dependencies are locked here rather than in the root project.

```bash
uv sync --frozen
PYTHONHASHSEED=0 uv run pytest
```

What each benchmark measures, how the baseline was captured, why the gate compares
ratios rather than wall time, and how to move the baseline are in
[../docs/BENCHMARKS.md](../docs/BENCHMARKS.md).

| File | What it is |
| --- | --- |
| `bench_*.py` | One benchmark each. |
| `applications.py` | The application shapes the benchmarks serve. |
| `harness.py` | Builds an application and drives one request through it. |
| `calibration.py` | The workload the gate divides by, so the machine cancels. |
| `gate.py` | Compares a run against `baseline.json` and fails on a regression. |
| `baseline.json` | The published baseline, captured on a CI runner, with the machine it was taken on. |
