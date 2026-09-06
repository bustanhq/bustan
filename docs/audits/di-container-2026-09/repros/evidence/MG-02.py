# ruff: noqa
# Evidence script for finding MG-02 (workflow id F-26) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-26: colliding exported tokens resolve first-wins silently; global loses to import; override refuses."""
import warnings
import logging
from bustan import Module, Global, create_app_context
from bustan.kernel.module.graph import build_module_graph
from bustan.kernel.ioc.container import build_container
from bustan.kernel.ioc.tokens import InjectionToken
from bustan.kernel.errors import ProviderResolutionError

logging.basicConfig(level=logging.DEBUG)
TOKEN = InjectionToken("CONFIG")


@Global()
@Module(providers=[{"provide": TOKEN, "use_value": "from-G1"}], exports=[TOKEN])
class G1:
    pass


@Global()
@Module(providers=[{"provide": TOKEN, "use_value": "from-G2"}], exports=[TOKEN])
class G2:
    pass


@Module()
class Consumer:
    pass


@Module(imports=[G2, G1, Consumer])
class AppG2G1:
    pass


@Module(imports=[G1, G2, Consumer])
class AppG1G2:
    pass


observed = {}
with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    for label, root in (("G2,G1", AppG2G1), ("G1,G2", AppG1G2)):
        try:
            c = build_container(build_module_graph(root))
            observed[label] = c.resolve(TOKEN, module=Consumer)
            print(f"globals imports=[{label}] -> Consumer resolves {observed[label]!r} (no exception)")
        except Exception as exc:
            observed[label] = f"ERROR {type(exc).__name__}: {exc}"
            print(f"globals imports=[{label}] -> raised {type(exc).__name__}: {exc}")
    print("warnings emitted:", len(caught))

print("---- two non-global imports exporting the same token ----")


@Module(providers=[{"provide": TOKEN, "use_value": "from-A"}], exports=[TOKEN])
class A:
    pass


@Module(providers=[{"provide": TOKEN, "use_value": "from-B"}], exports=[TOKEN])
class B:
    pass


@Module(imports=[A, B])
class AppAB:
    pass


@Module(imports=[B, A])
class AppBA:
    pass


for label, root in (("A,B", AppAB), ("B,A", AppBA)):
    c = build_container(build_module_graph(root))
    observed[label] = c.resolve(TOKEN, module=root)
    print(f"imports=[{label}] -> {observed[label]!r}")

print("---- global export loses to an import (global not imported directly by consumer) ----")


@Module(imports=[A])
class ConsumerImportsA:
    pass


@Module()
class ConsumerImportsNothing:
    pass


@Module(imports=[G1, ConsumerImportsA, ConsumerImportsNothing])
class AppGlobalVsImport:
    pass


c = build_container(build_module_graph(AppGlobalVsImport))
observed["consumer-imports-A"] = c.resolve(TOKEN, module=ConsumerImportsA)
observed["consumer-imports-nothing"] = c.resolve(TOKEN, module=ConsumerImportsNothing)
print("ConsumerImportsA sees", repr(observed["consumer-imports-A"]), "; ConsumerImportsNothing sees", repr(observed["consumer-imports-nothing"]))

print("---- global module imported directly: competes in import order ----")


@Module(imports=[G1, A])
class AppGA:
    pass


@Module(imports=[A, G1])
class AppAG:
    pass


observed["G1,A"] = build_container(build_module_graph(AppGA)).resolve(TOKEN, module=AppGA)
observed["A,G1"] = build_container(build_module_graph(AppAG)).resolve(TOKEN, module=AppAG)
print("imports=[G1(global), A] ->", repr(observed["G1,A"]), "; imports=[A, G1(global)] ->", repr(observed["A,G1"]))

print("---- override without module on the ambiguous token ----")
c = build_container(build_module_graph(AppAB))
try:
    c.override(TOKEN, "x")
    override_err = None
    print("override succeeded (unexpected)")
except ProviderResolutionError as exc:
    override_err = str(exc)
    print("override error:", exc)

ok = (
    observed.get("G2,G1") == "from-G2"
    and observed.get("G1,G2") == "from-G1"
    and observed.get("A,B") == "from-A"
    and observed.get("B,A") == "from-B"
    and observed.get("consumer-imports-A") == "from-A"
    and observed.get("consumer-imports-nothing") == "from-G1"
    and observed.get("G1,A") == "from-G1"
    and observed.get("A,G1") == "from-A"
    and override_err is not None and "multiple modules" in override_err
)
if ok:
    print("RESULT: CONFIRMED - collisions resolve first-wins by order with no exception/warning; global loses to import; override refuses")
else:
    print("RESULT: NOT CONFIRMED", observed, override_err)
