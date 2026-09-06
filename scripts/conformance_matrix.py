"""Run the adapter conformance suite over every adapter and require identical results.

The suite lives in ``bustan.platform.http.conformance``; this script is what runs it
against more than one adapter and refuses to pass when two of them answer the same case
differently. One adapter passing its own suite proves the suite runs. Two adapters
answering every case identically is what makes the abstraction a fact.

**What "identical" means here**, because a comparison nobody wrote down is a comparison
that gets argued about later. Two adapters are identical on a case when they agree on:

* the **status code**;
* the **body**, canonicalised - a JSON body compared as parsed JSON with sorted keys, so
  key order and whitespace are not read as a difference; any other body compared as its
  exact text;
* the **headers that case names**, and no others. Every case names the media type,
  because what a response says it is belongs to the framework's contract rather than to
  a server library's defaults; a case about a redirect names ``location``, a case about
  middleware names the header the middleware set.

Nothing else is compared, and that is deliberate. Header order, ``date``, ``server``,
``content-length``, ``etag``, the transfer encoding chosen for a streamed body and every
other header no contract names are the transport's own business: comparing them would
turn a server library's next release into a failing build with nothing to fix, and a
check that fails for reasons nobody can act on is a check that gets switched off. What
is compared is what an application written against this framework can observe and would
have to rewrite if it changed adapters.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from bustan.platform.http.conformance import (
    ADAPTER_NAMES,
    AdapterConformanceResult,
    describe_difference,
    evaluate_adapter_conformance,
    load_adapter,
)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the matrix and report every failure and every difference between adapters."""

    arguments = _parse_args(argv)
    adapters = tuple(arguments.adapters)
    if len(adapters) < 2:
        print(
            f"The matrix needs at least two adapters to compare; it was given {len(adapters)}.",
            file=sys.stderr,
        )
        return 1

    try:
        results = {name: evaluate_adapter_conformance(load_adapter(name)) for name in adapters}
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1

    problems = [*_failures(results), *_differences(adapters, results)]
    for problem in problems:
        print(problem)
    if problems:
        print(f"{len(problems)} conformance problems across {', '.join(adapters)}.")
        return 1

    case_count = len(next(iter(results.values())).checks)
    print(
        f"{case_count} conformance cases over {', '.join(adapters)}: "
        "every case passed and every adapter answered identically."
    )
    return 0


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Report failures and differences and exit non-zero on any (the default).",
    )
    parser.add_argument(
        "--adapters",
        nargs="+",
        default=list(ADAPTER_NAMES),
        metavar="NAME",
        help=f"Adapters to run the matrix over. Default: {' '.join(ADAPTER_NAMES)}",
    )
    return parser.parse_args(argv)


def _failures(results: dict[str, AdapterConformanceResult]) -> list[str]:
    """Report every case an adapter failed on its own terms, before any comparison.

    A case that failed for both adapters in the same way is not a difference, so it would
    survive the comparison unnoticed; it is reported here instead.
    """

    return [
        f"{check.name}: {adapter} failed the case: {check.detail}"
        for adapter, result in results.items()
        for check in result.checks
        if not check.passed
    ]


def _differences(
    adapters: Sequence[str], results: dict[str, AdapterConformanceResult]
) -> list[str]:
    """Report every case two adapters did not answer identically.

    Each adapter is compared against the first one named, so a case that three adapters
    answer three ways is reported twice rather than once and read as two differences.
    """

    baseline_name, *others = adapters
    baseline = results[baseline_name].observations()
    differences: list[str] = []
    for name in others:
        observations = results[name].observations()
        for case in sorted(set(baseline) | set(observations)):
            if case not in baseline or case not in observations:
                differences.append(f"{case}: run by one of {baseline_name}, {name} and not both")
                continue
            for detail in describe_difference(
                baseline_name, baseline[case], name, observations[case]
            ):
                differences.append(f"{case}: {baseline_name} and {name} differ - {detail}")
    return differences


if __name__ == "__main__":
    raise SystemExit(main())
