# ruff: noqa
# Evidence script for finding PN-06 (workflow id F-31) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-31: invalid dict-provider input escapes as raw TypeError/ValueError
instead of InvalidProviderError (unhashable provide tokens, bad scope strings).
Also compare with @Injectable(scope='Request') which raises InvalidProviderError."""
from bustan import Injectable, Module
from bustan.kernel.errors import BustanError, InvalidProviderError
from bustan.kernel.module.graph import build_module_graph

results = []


def try_build(providers, label):
    @Module(providers=providers)
    class Root:
        pass

    try:
        build_module_graph(Root)
        print(f"{label}: no error raised")
        return None
    except Exception as exc:  # noqa: BLE001
        is_bustan = isinstance(exc, BustanError)
        print(f"{label}: {type(exc).__module__}.{type(exc).__name__}: {exc}  (BustanError={is_bustan})")
        return exc


exc = try_build([{"provide": {"a": 1}, "use_value": 1}], "unhashable provide")
results.append(("unhashable provide -> raw TypeError, not BustanError",
                isinstance(exc, TypeError) and not isinstance(exc, BustanError)))

for bad_scope in ("Request", None, 1, "bogus"):
    exc = try_build([{"provide": "x", "use_class": object, "scope": bad_scope}], f"scope={bad_scope!r}")
    results.append((f"scope={bad_scope!r} -> raw ValueError, not BustanError",
                    isinstance(exc, ValueError) and not isinstance(exc, BustanError)))

# Contrast: the decorator form translates.
try:
    Injectable(scope="Request")
    dec_ok = False
    print("@Injectable(scope='Request'): no error")
except InvalidProviderError as exc:
    dec_ok = True
    print(f"@Injectable(scope='Request'): InvalidProviderError: {exc}")
results.append(("@Injectable(scope='Request') raises InvalidProviderError (inconsistent)", dec_ok))

# Control: the compiler DOES translate TypeError from normalize_provider.
exc = try_build([{"provide": "x"}], "missing use_* (control)")
results.append(("control: missing use_* -> InvalidProviderError", isinstance(exc, InvalidProviderError)))

print()
for label, ok in results:
    print(("CONFIRMED " if ok else "REFUTED   ") + label)
print("OVERALL:", "PASS (defect demonstrated)" if all(ok for _, ok in results) else "PARTIAL/FAIL")
