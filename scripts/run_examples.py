#!/usr/bin/env python3

"""Run every checked-in example: first its application, then the tests it ships.

Each example carries its own test file with real assertions. Running the application
alone proves only that it starts, and an unrun test suite is indistinguishable from a
passing one in a green build, so both halves run here and the count each suite
collected is printed. A suite that collects nothing fails: zero collected tests is
exactly the state this script exists to make visible, and nothing else reports it.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True, slots=True)
class Example:
    """One checked-in example project and the module its demo entry point lives in."""

    directory: str
    module: str

    @property
    def name(self) -> str:
        return Path(self.directory).name


@dataclass(frozen=True, slots=True)
class SuiteOutcome:
    """What one example's own pytest run reported.

    ``collected`` is the number of tests the run actually executed, read out of the
    JUnit report rather than scraped from the terminal summary. It is zero both when a
    suite has stopped being collected and when pytest never got far enough to write a
    report, and both of those are failures.
    """

    collected: int
    failures: int
    errors: int
    skipped: int
    exit_code: int

    @property
    def passed(self) -> bool:
        return self.exit_code == 0 and self.collected > 0 and self.failures == self.errors == 0


@dataclass(frozen=True, slots=True)
class ExampleOutcome:
    """One example's application run and test run, side by side."""

    example: Example
    application_exit_code: int
    suite: SuiteOutcome

    @property
    def passed(self) -> bool:
        return self.application_exit_code == 0 and self.suite.passed


EXAMPLES: tuple[Example, ...] = (
    Example("examples/blog_api", "blog_api.app"),
    Example("examples/multi_module_app", "multi_module_app.app"),
    Example("examples/graph_inspection", "graph_inspection.app"),
    Example("examples/request_scope_pipeline_app", "request_scope_pipeline_app.app"),
    Example("examples/testing_overrides", "testing_overrides.app"),
    Example("examples/dynamic_module_usage", "dynamic_module_usage.app"),
    Example("examples/link_shortener", "link_shortener.app"),
)


def _example_environment() -> dict[str, str]:
    environment = os.environ.copy()
    # Each example is a standalone uv project. An inherited VIRTUAL_ENV names the root
    # project's environment, which uv would warn about and then ignore.
    environment.pop("VIRTUAL_ENV", None)
    return environment


def _run(command: list[str], *, example: Example, environment: dict[str, str]) -> int:
    completed = subprocess.run(
        command,
        cwd=ROOT / example.directory,
        env=environment,
        check=False,
    )
    return completed.returncode


def run_application(example: Example, environment: dict[str, str]) -> int:
    """Run one example's demo entry point and return its exit code."""

    print(f"=== {example.name}: application", flush=True)
    return _run(
        ["uv", "run", "python", "-m", example.module],
        example=example,
        environment=environment,
    )


def run_suite(example: Example, environment: dict[str, str], report: Path) -> SuiteOutcome:
    """Run one example's own test suite and return what it reported."""

    print(f"=== {example.name}: tests", flush=True)
    exit_code = _run(
        ["uv", "run", "pytest", f"--junitxml={report}"],
        example=example,
        environment=environment,
    )
    if not report.exists():
        return SuiteOutcome(collected=0, failures=0, errors=0, skipped=0, exit_code=exit_code or 1)
    return _read_report(report, exit_code)


def _read_report(report: Path, exit_code: int) -> SuiteOutcome:
    root = ElementTree.parse(report).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))

    def total(attribute: str) -> int:
        return sum(int(suite.get(attribute, "0")) for suite in suites)

    return SuiteOutcome(
        collected=total("tests"),
        failures=total("failures"),
        errors=total("errors"),
        skipped=total("skipped"),
        exit_code=exit_code,
    )


def _print_summary(outcomes: list[ExampleOutcome]) -> None:
    header = f"{'example':<28}{'app':>5}{'collected':>11}{'failed':>8}{'errors':>8}{'skipped':>9}"
    print(flush=True)
    print(header, flush=True)
    print("-" * len(header), flush=True)
    for outcome in outcomes:
        suite = outcome.suite
        print(
            f"{outcome.example.name:<28}"
            f"{('ok' if outcome.application_exit_code == 0 else 'FAIL'):>5}"
            f"{suite.collected:>11}{suite.failures:>8}{suite.errors:>8}{suite.skipped:>9}",
            flush=True,
        )
    total_collected = sum(outcome.suite.collected for outcome in outcomes)
    print(f"\n{len(outcomes)} examples, {total_collected} tests collected", flush=True)


def _print_failures(outcomes: list[ExampleOutcome]) -> None:
    for outcome in outcomes:
        if outcome.application_exit_code != 0:
            print(
                f"FAIL {outcome.example.name}: application exited {outcome.application_exit_code}",
                flush=True,
            )
        suite = outcome.suite
        if suite.collected == 0:
            print(
                f"FAIL {outcome.example.name}: its test suite collected no tests, so "
                "nothing it asserts was evaluated",
                flush=True,
            )
        elif not suite.passed:
            print(
                f"FAIL {outcome.example.name}: {suite.failures} failed, {suite.errors} "
                f"errored, pytest exited {suite.exit_code}",
                flush=True,
            )


def main() -> int:
    environment = _example_environment()
    outcomes: list[ExampleOutcome] = []
    with tempfile.TemporaryDirectory() as reports:
        for example in EXAMPLES:
            application_exit_code = run_application(example, environment)
            suite = run_suite(example, environment, Path(reports) / f"{example.name}.xml")
            outcomes.append(
                ExampleOutcome(
                    example=example,
                    application_exit_code=application_exit_code,
                    suite=suite,
                )
            )

    _print_summary(outcomes)
    if all(outcome.passed for outcome in outcomes):
        return 0
    print(flush=True)
    _print_failures(outcomes)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
