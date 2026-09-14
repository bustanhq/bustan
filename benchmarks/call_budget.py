"""Hold every Bustan route to a budget of calls into bustan's own code, one request each.

A timing needs a threshold wide enough for the machine it ran on. A count does not: how many
of bustan's functions a request starts follows from the code and the locked dependencies,
not from how fast or how busy the machine is, so each route is held to its budget exactly
and one call over it fails.

A call counts when the function it starts is bustan's: written in the package's source, or
generated into one of its modules when a class was created, as a dataclass's ``__init__``
is. Calls into the application, the standard library and every other dependency are not
counted; the timings are what measure those.

    python call_budget.py            judge this tree against call_budget.json
    python call_budget.py --write    rewrite call_budget.json from this tree

A route under its budget passes and is named, so that the change which removed the calls can
lower the budget and hold the gain. How the budget moves is in docs/how-to/run-benchmarks.md.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from types import CodeType, FunctionType
from typing import TYPE_CHECKING

from applications import (
    HUNDRED_ITEMS_PATH,
    ITEM_PATH,
    HundredItemsModule,
    PipelineModule,
    RequestScopedModule,
    SimpleModule,
    SyncModule,
)
from harness import RequestDriver

import bustan

if TYPE_CHECKING:
    from collections.abc import Callable

BUDGET_PATH = Path(__file__).parent / "call_budget.json"
SCHEMA = 1

# Every Bustan route the suite times, by the benchmark that times it. Container resolution
# serves no request, so it has no route to hold to a budget.
ROUTES: dict[str, tuple[type[object], str]] = {
    "bench_hundred_items_route": (HundredItemsModule, HUNDRED_ITEMS_PATH),
    "bench_pipeline_route": (PipelineModule, ITEM_PATH),
    "bench_request_scoped_chain": (RequestScopedModule, ITEM_PATH),
    "bench_simple_route": (SimpleModule, ITEM_PATH),
    "bench_sync_route": (SyncModule, ITEM_PATH),
}

# The first request to a route builds what every later one reuses, so it starts more
# functions than the steady state a serving application is in. It is served before
# counting begins, and the requests counted after it must agree, or the count is no budget.
WARMUP_REQUESTS = 2
COUNTED_REQUESTS = 3

_PACKAGE = os.path.dirname(bustan.__file__) + os.sep
_TOOL = sys.monitoring.PROFILER_ID
_PY_START = sys.monitoring.events.PY_START


def count_calls(root_module: type[object], path: str) -> int:
    """Return how many of bustan's functions one warm request to ``path`` starts."""

    with RequestDriver.for_module(root_module, path) as driver:
        for _ in range(WARMUP_REQUESTS):
            driver.send_request()
        # Taken once the route is warm, when every class the request path touches has been
        # imported, and with it every method generated for one.
        is_bustan = _bustan_code()
        counts = {_count_one_request(driver, path, is_bustan) for _ in range(COUNTED_REQUESTS)}
    if len(counts) != 1:
        raise SystemExit(f"{path}: requests disagree on the count, {sorted(counts)}")
    return counts.pop()


def _count_one_request(
    driver: RequestDriver, path: str, is_bustan: Callable[[CodeType], bool]
) -> int:
    started: list[CodeType] = []
    sys.monitoring.use_tool_id(_TOOL, "bustan call budget")
    # Appended rather than counted in place, because the callback also runs on the worker
    # thread a synchronous handler is sent to, and an append is atomic where a sum is not.
    sys.monitoring.register_callback(_TOOL, _PY_START, lambda code, _: started.append(code))
    sys.monitoring.set_events(_TOOL, _PY_START)
    try:
        status = driver.send_request()
    finally:
        sys.monitoring.set_events(_TOOL, sys.monitoring.events.NO_EVENTS)
        sys.monitoring.register_callback(_TOOL, _PY_START, None)
        sys.monitoring.free_tool_id(_TOOL)
    if status != 200:
        raise SystemExit(f"{path} answered {status}, so what was counted is not the route")
    return sum(1 for code in started if is_bustan(code))


def _bustan_code() -> Callable[[CodeType], bool]:
    """Return a test for whether a code object is bustan's.

    Most of bustan's functions name a file in the package. A method generated when a class is
    created, such as a dataclass's ``__init__``, names none, but it is generated into the
    module that defines the class, so those are found through the classes each loaded bustan
    module defines. A function attached to such a class from any other module is not bustan's.
    """

    generated: set[CodeType] = set()
    for name, module in tuple(sys.modules.items()):
        if module is None or not (name == "bustan" or name.startswith("bustan.")):
            continue
        for owner in vars(module).values():
            if isinstance(owner, type) and owner.__module__ == name:
                generated.update(
                    member.__code__
                    for member in vars(owner).values()
                    if isinstance(member, FunctionType) and member.__module__ == name
                )
    return lambda code: code.co_filename.startswith(_PACKAGE) or code in generated


def write_budget(path: Path, counts: dict[str, int]) -> None:
    """Publish the counts as the budget every later run is held to."""

    document = {"schema": SCHEMA, "calls_per_request": dict(sorted(counts.items()))}
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {path}\n")
    for name, calls in sorted(counts.items()):
        print(f"{name:32} {calls:>7}")


def judge(path: Path, counts: dict[str, int]) -> int:
    """Print every route's count against its budget and fail a route that exceeds it."""

    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema") != SCHEMA:
        raise SystemExit(f"{path}: schema {document.get('schema')!r} is not supported")
    budget: dict[str, int] = document["calls_per_request"]
    failed, under = [], []
    print(f"{'route':32} {'budget':>7} {'counted':>8}  verdict")
    for name in sorted(budget.keys() | counts.keys()):
        allowed, counted = budget.get(name), counts.get(name)
        if allowed is None or counted is None:
            verdict = "NO BUDGET" if allowed is None else "NOT COUNTED"
            failed.append(name)
        elif counted > allowed:
            verdict = f"OVER BY {counted - allowed}"
            failed.append(name)
        else:
            verdict = "ok" if counted == allowed else f"under by {allowed - counted}"
            if counted < allowed:
                under.append(name)
        shown_allowed = "-" if allowed is None else allowed
        shown_counted = "-" if counted is None else counted
        print(f"{name:32} {shown_allowed:>7} {shown_counted:>8}  {verdict}")
    if under:
        print(f"\nunder budget: {', '.join(under)}; --write lowers the budget and holds the gain")
    if failed:
        print(f"\ncall budget failed: {', '.join(failed)}")
        return 1
    print("\ncall budget passed")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--budget", type=Path, default=BUDGET_PATH, metavar="PATH")
    arguments = parser.parse_args(argv)
    counts = {name: count_calls(module, path) for name, (module, path) in ROUTES.items()}
    if arguments.write:
        write_budget(arguments.budget, counts)
        return 0
    return judge(arguments.budget, counts)


if __name__ == "__main__":
    sys.exit(main())
