# ruff: noqa
# Evidence script for finding QA-11 (workflow id F-77) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-77: coverage gate prints FAIL but exits 0 because pytest-cov compares with precision=0 rounding."""
import os, re, subprocess, sys, tempfile
from coverage.results import should_fail_under

repo = "/home/user/bustan"
cov_file = os.path.join(tempfile.mkdtemp(prefix="f77-"), ".coverage")
env = dict(os.environ, COVERAGE_FILE=cov_file)
cmd = [sys.executable, "-m", "pytest", "--cov=bustan", "--cov-report=term-missing", "-q", "-p", "no:cacheprovider"]
proc = subprocess.run(cmd, cwd=repo, env=env, capture_output=True, text=True)
out = proc.stdout + proc.stderr
fail_line = next((l for l in out.splitlines() if "Required test coverage" in l), None)
total_line = next((l for l in out.splitlines() if l.startswith("TOTAL")), None)
summary = next((l for l in out.splitlines() if re.search(r"\d+ passed", l)), None)
print("pytest summary:", summary)
print("TOTAL line    :", total_line)
print("fail line     :", fail_line)
print("exit code     :", proc.returncode)
m = re.search(r"Total coverage: ([0-9.]+)%", fail_line or "")
total = float(m.group(1)) if m else None
print("unrounded total:", total)
if total is not None:
    print("should_fail_under(total, 95, precision=0) =", should_fail_under(total, 95, 0))
    print("should_fail_under(total, 95, precision=2) =", should_fail_under(total, 95, 2))
per_file = {}
for l in out.splitlines():
    for name in ("core/ioc/resolver.py", "core/ioc/scopes.py", "core/lifecycle/runner.py", "core/lifecycle/manager.py", "core/lifecycle/hooks.py"):
        if name in l:
            per_file[name] = l.split()[4] if len(l.split()) > 4 else l
print("kernel per-file coverage:", per_file)
try:
    os.remove(cov_file)
except OSError:
    pass
confirmed = fail_line is not None and "FAIL" in fail_line and proc.returncode == 0 and total is not None and total < 95
print("RESULT:", "CONFIRMED - 'FAIL Required test coverage' printed with total < 95 yet exit code 0" if confirmed else "REFUTED - gate behaves as advertised")
