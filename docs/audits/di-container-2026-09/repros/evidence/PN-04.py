# ruff: noqa
# Evidence script for finding PN-04 (workflow id F-32) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-32: dict provider normalization silently ignores 'inject' for use_class,
prioritizes the first use_* key, explodes a string 'inject' into characters,
and accepts non-class / non-callable targets that fail at resolve time."""
from bustan import Injectable, Module
from bustan.app.bootstrap import create_app_context
from bustan.core.errors import BustanError, ProviderResolutionError
from bustan.core.ioc.registry import normalize_provider

results = []


@Injectable()
class Dep:
    pass


class Svc:
    def __init__(self, dep: Dep) -> None:
        self.dep = dep


class Unrelated:
    pass


# 1. inject ignored for use_class
b = normalize_provider({"provide": "svc", "use_class": Svc, "inject": ["dep"]}, Unrelated)
print(f"1. use_class+inject -> kind={b.resolver_kind} target={b.target!r} (inject dropped)")
results.append(("inject silently dropped for use_class", b.resolver_kind == "class" and b.target is Svc))

# 2. multiple use_* keys: first in fixed order wins, silently
b = normalize_provider({"provide": "multi", "use_class": Svc, "use_value": 42, "use_factory": lambda: 1}, Unrelated)
print(f"2. use_class+use_value+use_factory -> kind={b.resolver_kind} (others dropped silently)")
results.append(("multiple use_* keys silently prioritized", b.resolver_kind == "class"))
b = normalize_provider({"provide": "unk", "use_value": 1, "totally_unknown": 5}, Unrelated)
print(f"2b. unknown key accepted silently -> kind={b.resolver_kind}")
results.append(("unknown keys ignored silently", b.resolver_kind == "value"))

# 3. string inject exploded into characters
b = normalize_provider({"provide": "f", "use_factory": lambda d: d, "inject": "dep"}, Unrelated)
print(f"3. inject='dep' -> inject tuple = {b.target[1]!r}")
results.append(("string inject exploded into characters", b.target[1] == ("d", "e", "p")))


@Module(providers=[{"provide": "dep", "use_value": "DEP"},
                   {"provide": "f", "use_factory": lambda d: d, "inject": "dep"}])
class RootStrInject:
    pass


ctx = create_app_context(RootStrInject)
try:
    ctx.get("f")
    print("3b. resolve 'f' succeeded unexpectedly")
    results.append(("string inject fails at resolve with 'd' not available", False))
except ProviderResolutionError as exc:
    print(f"3b. resolve 'f' -> ProviderResolutionError: {exc}")
    results.append(("string inject fails at resolve with 'd' not available", "'d'" in str(exc) or "d is not available" in str(exc)))

# 4. bad targets accepted at normalization, fail at resolve with non-Bustan errors
def resolve_bad(providers, token, label):
    @Module(providers=providers)
    class Root:
        pass

    try:
        c = create_app_context(Root)
    except Exception as exc:  # noqa: BLE001
        print(f"{label}: build_module_graph/container raised {type(exc).__name__}: {exc}")
        return exc, "build"
    try:
        v = c.get(token)
        print(f"{label}: resolved -> {v!r}")
        return None, "resolved"
    except Exception as exc:  # noqa: BLE001
        print(f"{label}: resolve raised {type(exc).__module__}.{type(exc).__name__}: {exc} (BustanError={isinstance(exc, BustanError)})")
        return exc, "resolve"


exc, where = resolve_bad([Dep, {"provide": "inst", "use_class": Svc(Dep())}], "inst", "4a. use_class=Svc() instance")
results.append(("use_class instance accepted, fails at resolve with non-Bustan error",
                where == "resolve" and exc is not None and not isinstance(exc, BustanError)))

exc, where = resolve_bad([{"provide": "fac", "use_factory": 42}], "fac", "4b. use_factory=42")
results.append(("use_factory=42 accepted, fails at resolve with non-Bustan error",
                where == "resolve" and exc is not None and not isinstance(exc, BustanError)))

# 4c. does the error message name the module?
if exc is not None:
    names_module = "Root" in str(exc)
    print(f"4c. error message names module: {names_module}")
    results.append(("error does not name the module", not names_module))

print()
for label, ok in results:
    print(("CONFIRMED " if ok else "REFUTED   ") + label)
print("OVERALL:", "PASS (defect demonstrated)" if all(ok for _, ok in results) else "PARTIAL/FAIL")
