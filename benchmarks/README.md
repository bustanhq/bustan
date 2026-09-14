# Benchmarks

A standalone `uv` project holding the framework's benchmark suite, the regression gate
that CI runs over it, and the budget of calls each route may make into `bustan`. It is not
collected by `pytest` at the repository root and its dependencies are locked here rather
than in the root project.

```bash
uv sync --frozen
PYTHONHASHSEED=0 uv run pytest
PYTHONHASHSEED=0 uv run python call_budget.py
```

What each benchmark measures, how the baseline was captured, how the call budget moves,
and how to move the baseline are in
[../docs/how-to/run-benchmarks.md](../docs/how-to/run-benchmarks.md).

| File | What it is |
| --- | --- |
| `bench_*.py` | One benchmark each. A name ending `_litestar` is Litestar serving the request the same name without it times. |
| `applications.py` | The Bustan application shapes the benchmarks serve. |
| `litestar_applications.py` | The Litestar twins of three of those routes. |
| `harness.py` | Builds an application and drives one request through it. |
| `calibration.py` | The workload the gate divides by, so the machine cancels. |
| `gate.py` | Compares a run against `baseline.json`, fails on a regression, and prints each route against its Litestar twin. |
| `baseline.json` | The published baseline, captured on a CI runner, with the machine it was taken on. |
| `call_budget.py` | Counts the calls one request makes into `bustan` on each route and fails a route over its budget. |
| `call_budget.json` | The committed budget: calls per request, per route. |
