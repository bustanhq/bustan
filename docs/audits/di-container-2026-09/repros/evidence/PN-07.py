# ruff: noqa
# Evidence script for finding PN-07 (workflow id F-54) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-54: __bustan_provider__ dict on the class is mutable and trusted verbatim."""
from bustan import Injectable, Module, create_app_context
from bustan.common.constants import BUSTAN_PROVIDER_ATTR
from bustan.kernel.errors import InvalidProviderError, InvalidModuleError

@Injectable
class Svc:
    pass

@Injectable
class Other:
    pass

meta = getattr(Svc, BUSTAN_PROVIDER_ATTR)
print(f"metadata type: {type(meta).__name__}; attr name: {BUSTAN_PROVIDER_ATTR}")

# Mutate use_class
meta["use_class"] = Other

@Module(providers=[Svc])
class M1:
    pass

ctx = create_app_context(M1)
inst = ctx.get(Svc)
print(f"after use_class mutation: ctx.get(Svc) -> {type(inst).__name__}")
case1 = type(inst) is Other

# Mutate token
@Injectable
class Svc2:
    pass
getattr(Svc2, BUSTAN_PROVIDER_ATTR)["token"] = "ALIAS"

@Module(providers=[Svc2])
class M2:
    pass
ctx2 = create_app_context(M2)
try:
    ctx2.get(Svc2)
    case2 = False
    print("after token mutation: Svc2 still resolvable by class (unexpected)")
except Exception as exc:
    alias = ctx2.get("ALIAS")
    print(f"after token mutation: get(Svc2) raised {type(exc).__name__}; get('ALIAS') -> {type(alias).__name__}")
    case2 = type(alias) is Svc2

# Invalid scope string
@Injectable
class Svc3:
    pass
getattr(Svc3, BUSTAN_PROVIDER_ATTR)["scope"] = "bogus"

@Module(providers=[Svc3])
class M3:
    pass
try:
    create_app_context(M3)
    print("bogus scope: accepted (unexpected)")
    case3 = False
except (InvalidProviderError, InvalidModuleError) as exc:
    print(f"bogus scope: framework error {type(exc).__name__}: {exc}")
    case3 = False
except ValueError as exc:
    print(f"bogus scope: raw ValueError: {exc}")
    case3 = True

# Contrast: controller metadata
from bustan import Controller
from bustan.common.constants import BUSTAN_CONTROLLER_ATTR
@Controller("/x")
class C:
    pass
cmeta = getattr(C, BUSTAN_CONTROLLER_ATTR)
print(f"controller metadata type: {type(cmeta).__name__}, frozen={getattr(type(cmeta), '__dataclass_params__', None) and type(cmeta).__dataclass_params__.frozen}")

if case1 and case2 and case3:
    print("FAIL (defect confirmed): mutable provider dict trusted verbatim; bogus scope surfaces as raw ValueError")
else:
    print(f"PASS/partial: case1={case1} case2={case2} case3={case3}")
