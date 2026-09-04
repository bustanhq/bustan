# ruff: noqa
# Evidence script for finding PN-11 (workflow id F-90) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
# F-90: tokens are keyed by equality, so StrEnum members alias bare strings
# (and True aliases 1). A local 'db' binding shadows an imported Tokens.DB
# export without diagnostic; both in one module is a 'duplicate'; and
# OverrideManager (identity match) then targets the wrong binding.
from enum import StrEnum

from bustan import Module
from bustan.app.bootstrap import create_app_context
from bustan.core.errors import InvalidModuleError, ProviderResolutionError


class Tokens(StrEnum):
    DB = "db"


@Module(providers=[{"provide": Tokens.DB, "use_value": "enum-db"}], exports=[Tokens.DB])
class SharedModule:
    pass


@Module(imports=[SharedModule], providers=[{"provide": "db", "use_value": "string-db"}])
class FeatureModule:
    pass


results: dict[str, object] = {}
ctx = create_app_context(FeatureModule)
print("Tokens.DB == 'db':", Tokens.DB == "db", "| hash equal:", hash(Tokens.DB) == hash("db"), "| identity:", Tokens.DB is "db")
enum_lookup = ctx.get(Tokens.DB)
str_lookup = ctx.get("db")
vis = ctx.container.registry.module_visibility[FeatureModule]
print("FeatureModule.get(Tokens.DB) ->", repr(enum_lookup))
print("FeatureModule.get('db')      ->", repr(str_lookup))
print("visibility for FeatureModule:", {repr(k): v.__name__ for k, v in vis.items()})
results["shadow"] = enum_lookup

# duplicate detection inside one module
try:
    @Module(providers=[{"provide": Tokens.DB, "use_value": 1}, {"provide": "db", "use_value": 2}])
    class Dup:
        pass

    create_app_context(Dup)
    results["dup"] = "accepted"
except InvalidModuleError as exc:
    results["dup"] = "InvalidModuleError"
    print("enum + string token in one module ->", type(exc).__name__ + ":", str(exc)[:120])

# override manager identity mismatch: which binding does override(Tokens.DB) hit?
try:
    ctx.container.override(Tokens.DB, "fake")
    after = ctx.get(Tokens.DB)
    print("override(Tokens.DB, 'fake') accepted; FeatureModule.get(Tokens.DB) ->", repr(after))
    print("  override registered on module:", ctx.container.overrides.get_override(Tokens.DB) if hasattr(ctx.container, "overrides") else "n/a")
    print("  SharedModule.resolve(Tokens.DB) ->", repr(ctx.container.resolve(Tokens.DB, module=SharedModule)))
    results["override_after"] = after
except ProviderResolutionError as exc:
    results["override_after"] = "ProviderResolutionError: " + str(exc)[:100]
    print("override(Tokens.DB) ->", str(exc)[:120])

# True / 1 aliasing
@Module(providers=[{"provide": 1, "use_value": "int-one"}], exports=[1])
class IntModule:
    pass


@Module(imports=[IntModule], providers=[{"provide": True, "use_value": "bool-true"}])
class BoolModule:
    pass


ctx2 = create_app_context(BoolModule)
print("BoolModule.get(1) ->", repr(ctx2.get(1)), "| get(True) ->", repr(ctx2.get(True)))
results["int_bool"] = ctx2.get(1)

ok = (
    results["shadow"] == "string-db"
    and results["dup"] == "InvalidModuleError"
    and results["override_after"] == "string-db"
    and results["int_bool"] == "bool-true"
)
print("RESULT:", "PASS (defect reproduced)" if ok else "FAIL (defect not reproduced)", results)
