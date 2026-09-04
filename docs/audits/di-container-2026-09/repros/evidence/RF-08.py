# ruff: noqa
# Evidence script for finding RF-08 (workflow id F-56) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-56: class overriding __new__ but keeping object.__init__ bypasses injection."""
from dataclasses import dataclass
from bustan import Injectable, Module, create_app_context
from bustan.core.errors import ProviderResolutionError

@Injectable
class Dep:
    pass

@Injectable
class NewOnly:
    def __new__(cls, dep: Dep):
        self = super().__new__(cls)
        self.dep = dep
        return self

@Module(providers=[Dep, NewOnly])
class M:
    pass

ctx = create_app_context(M)
print(f"NewOnly.__init__ is object.__init__: {NewOnly.__init__ is object.__init__}")
try:
    inst = ctx.get(NewOnly)
    print(f"resolved NewOnly with dep={type(inst.dep).__name__}")
    print("PASS (refuted): injection through __new__ works")
except ProviderResolutionError as exc:
    print(f"PASS-ish (refuted as described): framework error ProviderResolutionError: {exc}")
except TypeError as exc:
    print(f"raw TypeError: {exc}")
    print("FAIL (defect confirmed): __new__ dependencies neither injected nor rejected with a framework error")

# Controls: dataclass and __slots__
@Injectable
@dataclass
class DC:
    dep: Dep

@Injectable
class Slotted:
    __slots__ = ("dep",)
    def __init__(self, dep: Dep) -> None:
        self.dep = dep

@Module(providers=[Dep, DC, Slotted])
class M2:
    pass
ctx2 = create_app_context(M2)
print(f"control dataclass ok: {type(ctx2.get(DC).dep).__name__}; slots ok: {type(ctx2.get(Slotted).dep).__name__}")
