# ruff: noqa
# Evidence script for finding MG-08 (workflow id F-53) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-53: DynamicModule cannot override a base provider token or re-add a base import."""
from bustan import DynamicModule, InjectionToken, Module, create_app_context
from bustan.core.errors import InvalidModuleError

OPTS = InjectionToken("OPTS")
results = []

# Case 1: base declares default OPTS, dynamic overlay re-declares OPTS
@Module(providers=[{"provide": OPTS, "use_value": "default"}], exports=[OPTS])
class Base:
    pass

dyn = DynamicModule(Base, providers=({"provide": OPTS, "use_value": "dyn"},))
try:
    ctx = create_app_context(dyn)
    value = ctx.get(OPTS)
    print(f"case1 provider override: resolved OPTS={value!r} (no error)")
    results.append(("case1", value == "dyn"))
except InvalidModuleError as exc:
    print(f"case1 provider override: InvalidModuleError: {exc}")
    results.append(("case1", False))

# Case 2: base imports Shared; dynamic overlay also lists Shared in imports
@Module(providers=[{"provide": "S", "use_value": 1}], exports=["S"])
class Shared:
    pass

@Module(imports=[Shared])
class Base2:
    pass

dyn2 = DynamicModule(Base2, imports=(Shared,))
try:
    ctx = create_app_context(dyn2)
    print(f"case2 duplicate import: ok, S={ctx.get('S')!r}")
    results.append(("case2", True))
except InvalidModuleError as exc:
    print(f"case2 duplicate import: InvalidModuleError: {exc}")
    results.append(("case2", False))

# Case 3 (control): exports ARE deduplicated
@Module(providers=[{"provide": "E", "use_value": 5}], exports=["E"])
class Base3:
    pass

dyn3 = DynamicModule(Base3, exports=("E",))
try:
    create_app_context(dyn3)
    print("case3 duplicate export: accepted (deduplicated)")
    results.append(("case3", True))
except InvalidModuleError as exc:
    print(f"case3 duplicate export: InvalidModuleError: {exc}")
    results.append(("case3", False))

# Case 4: ConfigurableModuleBuilder base is empty, so for_root works
from bustan import ConfigurableModuleBuilder
from bustan.core.module.metadata import get_module_metadata
Gen, TOKEN = ConfigurableModuleBuilder().set_class_name("Cfg").build()
meta = get_module_metadata(Gen)
print(f"case4 generated base providers={meta.providers!r} imports={meta.imports!r}")

failed = [name for name, ok in results if not ok]
if ("case1" in failed or "case2" in failed) and "case3" not in failed:
    print("FAIL (defect confirmed): dynamic overlay cannot override base provider token / re-add base import, while exports are deduplicated")
else:
    print("PASS (defect refuted): framework accepts overlay override")
