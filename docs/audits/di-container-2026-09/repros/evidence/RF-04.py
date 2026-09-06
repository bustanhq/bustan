# ruff: noqa
# Evidence script for finding RF-04 (workflow id F-35) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-35: constructor parameter defaults are ignored by _plan_constructor_parameters."""
from __future__ import annotations
from typing import Annotated
from bustan import Injectable, Module, Inject, OptionalDep, create_app_context
from bustan.kernel.errors import ProviderResolutionError

class NotProvided:
    pass

@Injectable
class AnnotatedValueDefault:
    def __init__(self, retries: int = 3) -> None:
        self.retries = retries

@Injectable
class NoAnnotationDefault:
    def __init__(self, retries=3) -> None:
        self.retries = retries

@Injectable
class UnionNoneDefault:
    def __init__(self, dep: NotProvided | None = None) -> None:
        self.dep = dep

SENTINEL = object()

@Injectable
class OptionalDepWithDefault:
    def __init__(self,
                 dep: Annotated[NotProvided, OptionalDep()] = SENTINEL,
                 limit: Annotated[int, Inject("LIMIT"), OptionalDep()] = 10) -> None:
        self.dep = dep
        self.limit = limit

results = {}
for cls in (AnnotatedValueDefault, NoAnnotationDefault, UnionNoneDefault):
    @Module(providers=[cls])
    class M: ...
    try:
        inst = create_app_context(M).get(cls)
        results[cls.__name__] = "ok " + str(vars(inst))
    except ProviderResolutionError as exc:
        results[cls.__name__] = "FAILED: " + str(exc)[:130]
    print(cls.__name__, "->", results[cls.__name__])

@Module(providers=[OptionalDepWithDefault])
class MO: ...
s = create_app_context(MO).get(OptionalDepWithDefault)
print("OptionalDepWithDefault -> dep is SENTINEL:", s.dep is SENTINEL, "| dep =", s.dep,
      "| limit =", s.limit, "(declared default 10)")

defaults_ignored = (
    results["AnnotatedValueDefault"].startswith("FAILED")
    and results["NoAnnotationDefault"].startswith("FAILED")
    and s.dep is None and s.limit is None
)
print("RESULT:", "CONFIRMED - defaults never applied; OptionalDep substitutes None over declared default"
      if defaults_ignored else "REFUTED - some defaults honored: " + str(results))
