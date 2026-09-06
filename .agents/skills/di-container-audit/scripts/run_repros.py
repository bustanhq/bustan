#!/usr/bin/env python3
"""Run every DI-audit repro script and summarize which defects still reproduce.

Each repro script prints one or more lines of the form:

    RESULT: <finding-id> REPRODUCED|FIXED|ERROR - <message>

The runner executes every ``*.py`` file in the given directory (default:
docs/audits/di-container-2026-09/repros) with the current interpreter,
collects those lines, and exits non-zero when any finding still reproduces.
Pass ``--expect-fixed`` to turn the harness into a regression gate.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

RESULT_RE = re.compile(r"^RESULT: (?P<id>\S+) (?P<status>REPRODUCED|FIXED|ERROR) - (?P<msg>.*)$")
DEFAULT_DIR = (
    Path(__file__).resolve().parents[4] / "docs" / "audits" / "di-container-2026-09" / "repros"
)


def run_script(path: Path, timeout: float) -> tuple[list[tuple[str, str, str]], str]:
    """Run one repro script and return its RESULT lines plus raw output."""
    try:
        completed = subprocess.run(
            [sys.executable, str(path)],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return [(path.stem, "ERROR", f"timed out after {timeout:.0f}s")], ""

    output = completed.stdout + completed.stderr
    results = [
        (m.group("id"), m.group("status"), m.group("msg"))
        for m in (RESULT_RE.match(line.strip()) for line in output.splitlines())
        if m is not None
    ]
    if not results:
        detail = output.strip().splitlines()[-1] if output.strip() else "no output"
        results = [(path.stem, "ERROR", f"no RESULT line (exit {completed.returncode}): {detail}")]
    return results, output


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("directory", nargs="?", default=str(DEFAULT_DIR))
    parser.add_argument(
        "--timeout", type=float, default=120.0, help="per-script timeout in seconds"
    )
    parser.add_argument("--verbose", action="store_true", help="print full script output")
    parser.add_argument(
        "--expect-fixed",
        action="store_true",
        help=(
            "exit non-zero when any finding still reproduces (default: exit non-zero on ERROR only)"
        ),
    )
    args = parser.parse_args()

    directory = Path(args.directory)
    scripts = sorted(p for p in directory.glob("*.py") if not p.name.startswith("_"))
    if not scripts:
        print(f"No repro scripts found in {directory}")
        return 2

    rows: list[tuple[str, str, str, str]] = []
    for script in scripts:
        results, output = run_script(script, args.timeout)
        if args.verbose:
            print(f"===== {script.name}\n{output}")
        for finding_id, status, message in results:
            rows.append((script.name, finding_id, status, message))

    width = max(len(r[1]) for r in rows)
    print(f"{'finding':<{width}}  {'status':<10}  script / message")
    for script_name, finding_id, status, message in rows:
        print(f"{finding_id:<{width}}  {status:<10}  {script_name}: {message}")

    reproduced = sum(1 for r in rows if r[2] == "REPRODUCED")
    errors = sum(1 for r in rows if r[2] == "ERROR")
    fixed = sum(1 for r in rows if r[2] == "FIXED")
    print(
        f"\n{reproduced} reproduced, {fixed} fixed, {errors} errors across {len(scripts)} scripts"
    )
    if errors:
        return 1
    if args.expect_fixed and reproduced:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
