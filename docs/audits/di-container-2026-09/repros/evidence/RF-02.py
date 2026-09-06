# ruff: noqa
# Evidence script for finding RF-02 (workflow id F-13) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-13: Optional[X] / X | None annotations are treated as tokens; Annotated[X | None, OptionalDep()] injects None even when X is provided."""
from __future__ import annotations

from typing import Annotated, Optional

from bustan import Injectable, Module, OptionalDep, create_app_context
from bustan.kernel.errors import ProviderResolutionError


@Injectable
class Dep:
    pass


@Injectable
class UsesOptional:
    def __init__(self, dep: Optional[Dep]) -> None:
        self.dep = dep


@Injectable
class UsesPipeNone:
    def __init__(self, dep: Dep | None) -> None:
        self.dep = dep


@Injectable
class UsesPipeNoneWithOptionalDep:
    def __init__(self, dep: Annotated[Dep | None, OptionalDep()]) -> None:
        self.dep = dep


@Injectable
class UsesPlainWithOptionalDep:  # control: OptionalDep on a plain class annotation
    def __init__(self, dep: Annotated[Dep, OptionalDep()]) -> None:
        self.dep = dep


results: dict[str, str] = {}
for cls in (UsesOptional, UsesPipeNone, UsesPipeNoneWithOptionalDep, UsesPlainWithOptionalDep):

    @Module(providers=[Dep, cls])
    class M:
        pass

    try:
        inst = create_app_context(M).get(cls)
        results[cls.__name__] = f"dep={inst.dep!r}"
        print(f"{cls.__name__}: constructed, dep = {inst.dep!r}")
    except ProviderResolutionError as exc:
        results[cls.__name__] = f"ERROR: {exc}"
        print(f"{cls.__name__}: ProviderResolutionError: {exc}")

optional_raises = results["UsesOptional"].startswith("ERROR") and "not available" in results["UsesOptional"]
pipe_raises = results["UsesPipeNone"].startswith("ERROR") and "not available" in results["UsesPipeNone"]
silent_none = results["UsesPipeNoneWithOptionalDep"] == "dep=None"
control_ok = results["UsesPlainWithOptionalDep"].startswith("dep=<")

print()
print("Optional[Dep] raises 'not available' although Dep is provided:", optional_raises)
print("Dep | None raises 'not available' although Dep is provided:  ", pipe_raises)
print("Annotated[Dep | None, OptionalDep()] silently injected None: ", silent_none)
print("control Annotated[Dep, OptionalDep()] injected a Dep:        ", control_ok)
confirmed = optional_raises and pipe_raises and silent_none and control_ok
print("F-13", "CONFIRMED" if confirmed else "REFUTED")
