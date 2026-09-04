# ruff: noqa
# Evidence script for finding PN-03 (workflow id F-30) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-30: OverrideManager matches tokens by identity ('is') while the registry
matches by equality, so equal-but-not-identical string/int tokens cannot be
overridden; has_override silently returns False; clear_override raises."""
from bustan import Module
from bustan.app.bootstrap import create_app_context
from bustan.core.errors import ProviderResolutionError
from bustan.testing.overrides import override_provider

results = []

literal_token = "client"
runtime_token = "".join(["cli", "ent"])
big_literal = 100000
big_runtime = int("100000")
assert literal_token == runtime_token and literal_token is not runtime_token
assert big_literal == big_runtime and big_literal is not big_runtime


@Module(
    providers=[
        {"provide": literal_token, "use_value": "real"},
        {"provide": big_literal, "use_value": "real-int"},
    ]
)
class Root:
    pass


ctx = create_app_context(Root)
c = ctx.container

# Registry/resolution use equality: runtime token resolves.
print(f"ctx.get(runtime_token)      -> {ctx.get(runtime_token)!r}")
print(f"ctx.get(big_runtime)        -> {ctx.get(big_runtime)!r}")

# Override path uses identity.
try:
    c.override(runtime_token, "fake")
    override_str_failed = False
    print("override(runtime_token) succeeded")
except ProviderResolutionError as exc:
    override_str_failed = True
    print(f"override(runtime_token) raised ProviderResolutionError: {exc}")
results.append(("override with equal-but-not-identical str token fails", override_str_failed))

print(f"has_override(runtime_token) -> {c.has_override(runtime_token)}")
results.append(("has_override silently False for runtime str", c.has_override(runtime_token) is False))

try:
    c.override(big_runtime, "fake-int")
    override_int_failed = False
    print("override(big_runtime) succeeded")
except ProviderResolutionError as exc:
    override_int_failed = True
    print(f"override(big_runtime) raised ProviderResolutionError: {exc}")
results.append(("override with equal-but-not-identical int token fails", override_int_failed))

# Literal (interned) token works, proving the identity dependence.
c.override(literal_token, "fake")
print(f"override(literal_token) ok; ctx.get(runtime_token) -> {ctx.get(runtime_token)!r}")
literal_ok = ctx.get(runtime_token) == "fake"
results.append(("override with identical literal token works (identity dependence)", literal_ok))
c.clear_override(literal_token)

# clear_override with runtime token raises (has_override swallows, clear does not).
try:
    c.clear_override(runtime_token)
    clear_raises = False
    print("clear_override(runtime_token) did not raise")
except ProviderResolutionError as exc:
    clear_raises = True
    print(f"clear_override(runtime_token) raised: {exc}")
results.append(("clear_override raises for runtime token", clear_raises))

# testing.override_provider context manager: has_override False -> override raises.
try:
    with override_provider(c, runtime_token, "fake2"):
        pass
    cm_failed = False
    print("override_provider(runtime_token) succeeded")
except ProviderResolutionError as exc:
    cm_failed = True
    print(f"override_provider(runtime_token) raised: {exc}")
results.append(("bustan.testing.override_provider fails for runtime token", cm_failed))

# Explicit module= path also goes through 'in self.registry.bindings' (equality) -> works?
try:
    c.override(runtime_token, "fake3", module=Root)
    print(f"override(runtime_token, module=Root) ok; ctx.get -> {ctx.get(runtime_token)!r}")
    module_path_ok = ctx.get(runtime_token) == "fake3"
    c.clear_override(runtime_token, module=Root)
except ProviderResolutionError as exc:
    module_path_ok = False
    print(f"override(runtime_token, module=Root) raised: {exc}")
print(f"note: explicit module= workaround works = {module_path_ok}")

print()
for label, ok in results:
    print(("CONFIRMED " if ok else "REFUTED   ") + label)
print("OVERALL:", "PASS (defect demonstrated)" if all(ok for _, ok in results) else "PARTIAL/FAIL")
