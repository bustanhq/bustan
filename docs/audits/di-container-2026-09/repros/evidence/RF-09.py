# ruff: noqa
# Evidence script for finding RF-09 (workflow id F-55) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-55: multiple Inject markers on one Annotated parameter; last wins silently."""
import warnings
from typing import Annotated
from bustan import Inject, Injectable, Module, create_app_context

@Injectable
class Consumer:
    def __init__(self, value: Annotated[str, Inject("A"), Inject("B")]) -> None:
        self.value = value

@Module(providers=[
    {"provide": "A", "use_value": "from-A"},
    {"provide": "B", "use_value": "from-B"},
    Consumer,
])
class M:
    pass

with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    try:
        ctx = create_app_context(M)
        c = ctx.get(Consumer)
        print(f"resolved value={c.value!r}; warnings emitted={len(caught)}")
        if c.value == "from-B" and not caught:
            print("FAIL (defect confirmed): conflicting Inject markers accepted silently, last marker wins")
        else:
            print("PASS: framework rejected or warned about conflicting markers")
    except Exception as exc:
        print(f"PASS (refuted): raised {type(exc).__name__}: {exc}")
