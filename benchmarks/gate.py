"""Compare a benchmark run against the published baseline and fail on a regression.

Every gated number is a ratio: the benchmark's median divided by the median of the
calibration workload measured in the same run. Dividing by the calibration is what makes
the comparison portable, because the baseline was captured on one machine and the gate
runs on another whose absolute speed nobody controls.

Run it after the suite:

    python gate.py --result run-1.json --result run-2.json

Given more than one result file it takes the lowest ratio each benchmark reached, so a
single pass that landed next to a noisy neighbour cannot fail the build on its own.

    python gate.py --result ... --write-baseline

republishes the baseline instead of judging against it, using the median ratio across the
files it was given. That is how the committed baseline was produced, and it is the only
supported way to move it.
"""

from __future__ import annotations

import argparse
import itertools
import json
import statistics
import sys
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

BASELINE_PATH = Path(__file__).parent / "baseline.json"
CALIBRATION = "bench_calibration"
STATISTIC = "median"
SCHEMA = 1

# Recorded in the baseline and copied out of it here so that the number a reader sees in
# the file is the number the gate applies. How it was chosen is in docs/BENCHMARKS.md.
DEFAULT_THRESHOLD = 0.30

_MACHINE_FIELDS = (
    "node",
    "processor",
    "machine",
    "system",
    "release",
    "python_implementation",
    "python_version",
    "python_compiler",
    "python_hash_seed",
)


def read_medians(path: Path) -> dict[str, float]:
    """Return the median of every benchmark in one result file, in seconds."""

    document = json.loads(path.read_text(encoding="utf-8"))
    return {entry["name"]: float(entry["stats"][STATISTIC]) for entry in document["benchmarks"]}


def read_pass(path: Path) -> dict[str, float]:
    """Return one result file as a ratio per benchmark, calibration divided out."""

    medians = read_medians(path)
    calibration = medians.pop(CALIBRATION, None)
    if not calibration:
        raise SystemExit(f"{path}: no {CALIBRATION} measurement, so nothing can be normalized")
    return {name: median / calibration for name, median in medians.items()}


def read_machine(path: Path) -> dict[str, Any]:
    """Return the machine and interpreter fields a baseline records."""

    machine_info = json.loads(path.read_text(encoding="utf-8"))["machine_info"]
    recorded = {field: machine_info.get(field) for field in _MACHINE_FIELDS}
    cpu = machine_info.get("cpu") or {}
    recorded["cpu_brand"] = cpu.get("brand_raw")
    recorded["cpu_count"] = cpu.get("count")
    return recorded


def combine(
    passes: list[dict[str, float]], reducer: Callable[[Iterable[float]], float]
) -> dict[str, float]:
    """Reduce the per-pass ratios of each benchmark to one number."""

    names = sorted({name for one_pass in passes for name in one_pass})
    return {name: reducer([p[name] for p in passes if name in p]) for name in names}


def write_baseline(paths: list[Path], threshold: float) -> None:
    """Publish the median ratio across the given result files as the new baseline."""

    passes = [read_pass(path) for path in paths]
    seconds = combine([read_medians(path) for path in paths], statistics.median)
    document = {
        "schema": SCHEMA,
        "statistic": STATISTIC,
        "calibration": CALIBRATION,
        "threshold": threshold,
        "passes": len(passes),
        "captured_on": read_machine(paths[0]),
        "ratios": {
            name: round(value, 5) for name, value in combine(passes, statistics.median).items()
        },
        # Published for a reader, not read by the gate: an absolute number is what says
        # whether the framework is fast, and a ratio never can.
        "medians_seconds": {name: float(f"{value:.4g}") for name, value in seconds.items()},
    }
    BASELINE_PATH.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"wrote {BASELINE_PATH} from {len(passes)} pass(es)\n")
    report_spread(passes, document["ratios"])


def report_spread(passes: list[dict[str, float]], baseline: dict[str, float]) -> None:
    """Print the run-to-run spread the capture saw, which is what a threshold is chosen from.

    The column to read is the last one, because the gate judges the lowest ratio across two
    passes rather than one pass on its own. A threshold has to clear that number with room
    to spare on a runner busier than the one the capture ran on, and it has to stay well
    under the smallest regression worth catching. Both halves are a judgement; this table
    is the evidence the judgement is made against.
    """

    header = f"{'benchmark':32} {'baseline':>9} {'lowest':>8} {'highest':>8} {'spread':>7}"
    print(header + f" {'worst pass':>11} {'worst of two':>13}")
    for name in sorted(baseline):
        seen = [one_pass[name] for one_pass in passes if name in one_pass]
        pairs = [min(pair) for pair in itertools.combinations(seen, 2)] or seen
        print(
            f"{name:32} {baseline[name]:9.4f} {min(seen):8.4f} {max(seen):8.4f} "
            f"{max(seen) / min(seen) - 1:6.1%} {max(seen) / baseline[name] - 1:+10.1%} "
            f"{max(pairs) / baseline[name] - 1:+12.1%}"
        )


def report(baseline: dict[str, float], observed: dict[str, float], threshold: float) -> list[str]:
    """Print the comparison table and return the benchmarks that breached the threshold."""

    breached = []
    print(f"{'benchmark':32} {'baseline':>10} {'observed':>10} {'change':>9}  verdict")
    for name in sorted(baseline):
        if name not in observed:
            breached.append(name)
            print(f"{name:32} {baseline[name]:10.4f} {'missing':>10} {'-':>9}  NOT RUN")
            continue
        change = observed[name] / baseline[name] - 1.0
        over = change > threshold
        if over:
            breached.append(name)
        print(
            f"{name:32} {baseline[name]:10.4f} {observed[name]:10.4f} "
            f"{change:+8.1%}  {'REGRESSED' if over else 'ok'}"
        )
    return breached


def check(paths: list[Path]) -> int:
    """Judge the given result files against the committed baseline."""

    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    if baseline.get("schema") != SCHEMA:
        raise SystemExit(f"{BASELINE_PATH}: schema {baseline.get('schema')!r} is not supported")
    threshold = float(baseline["threshold"])
    observed = combine([read_pass(path) for path in paths], min)
    _warn_on_unpinned_hash_seed(baseline, paths)
    print(f"threshold: a benchmark may not exceed its baseline ratio by more than {threshold:.0%}")
    print(f"observed: the lowest ratio each benchmark reached across {len(paths)} pass(es)\n")
    breached = report(baseline["ratios"], observed, threshold)
    if breached:
        print("\nregression gate failed: " + ", ".join(breached))
        return 1
    print("\nregression gate passed")
    return 0


def _warn_on_unpinned_hash_seed(baseline: dict[str, Any], paths: list[Path]) -> None:
    """Say so when a run was measured under a different hash seed than the baseline.

    Dictionary layout follows the hash seed and the framework's hot path is dictionaries,
    so an unpinned seed is worth several percent of run-to-run spread that the threshold
    would otherwise have to absorb.
    """

    expected = baseline.get("captured_on", {}).get("python_hash_seed")
    for path in paths:
        actual = read_machine(path).get("python_hash_seed")
        if actual != expected:
            print(f"warning: {path} ran with PYTHONHASHSEED={actual}, baseline used {expected}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", action="append", type=Path, required=True, metavar="PATH")
    parser.add_argument("--write-baseline", action="store_true")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    arguments = parser.parse_args(argv)
    if arguments.write_baseline:
        write_baseline(arguments.result, arguments.threshold)
        return 0
    return check(arguments.result)


if __name__ == "__main__":
    sys.exit(main())
