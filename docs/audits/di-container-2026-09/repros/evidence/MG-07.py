# ruff: noqa
# Evidence script for finding MG-07 (workflow id F-50) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-50: exporting a module class / DynamicModule (NestJS-style re-export) is rejected with a
misleading provider-flavoured ExportViolationError, and following TROUBLESHOOTING.md's advice
(add it to providers) produces a nonsensical class binding of the module class.
"""
from __future__ import annotations

from bustan import DynamicModule, Injectable, Module
from bustan.kernel.errors import ExportViolationError, InvalidModuleError
from bustan.kernel.module.graph import build_module_graph

results: dict[str, bool] = {}


@Injectable()
class Svc:
    pass


@Module(providers=[Svc], exports=[Svc])
class SharedModule:
    pass


@Module(imports=[SharedModule], exports=[SharedModule])
class CoreModule:
    pass


@Module(imports=[CoreModule])
class App:
    pass


print("--- 1. exports=[SharedModule] (module class) ---")
try:
    build_module_graph(App)
    print("accepted (module re-export works)")
    results["class_export_rejected"] = False
except ExportViolationError as exc:
    print("ExportViolationError:", exc)
    results["class_export_rejected"] = True
    results["class_msg_says_provider"] = "provider" in str(exc)
except InvalidModuleError as exc:
    print("InvalidModuleError (targeted):", exc)
    results["class_export_rejected"] = False

print("--- 2. exports=[DynamicModule(...)] ---")
dm = DynamicModule(SharedModule, providers=({"provide": "CFG", "use_value": 1},), exports=("CFG",))
# note: DynamicModule(..., providers=[list]) is unhashable and frozenset(metadata.exports) at graph.py:190
# then raises a raw TypeError - a side issue observed while writing this script.


@Module(imports=[dm], exports=[dm])
class Core2:
    pass


try:
    build_module_graph(Core2)
    print("accepted")
    results["dyn_export_rejected"] = False
except TypeError as exc:
    print("raw TypeError:", exc)
    results["dyn_export_rejected"] = True
    results["dyn_msg_has_dataclass_repr"] = False
except ExportViolationError as exc:
    msg = str(exc)
    print("ExportViolationError:", msg)
    results["dyn_export_rejected"] = True
    results["dyn_msg_has_dataclass_repr"] = "DynamicModule(module=" in msg
except InvalidModuleError as exc:
    print("InvalidModuleError (targeted):", exc)
    results["dyn_export_rejected"] = False

print("--- 3. follow TROUBLESHOOTING.md advice: add the module class to providers ---")


@Module(imports=[SharedModule], providers=[SharedModule], exports=[SharedModule])
class CoreFollowingDocs:
    pass


@Module(imports=[CoreFollowingDocs])
class App3:
    pass


try:
    graph = build_module_graph(App3)
    node = graph.get_node(CoreFollowingDocs)
    binding = node.bindings[0]
    print("graph accepted; CoreFollowingDocs binding:", binding.token, binding.resolver_kind,
          binding.scope, "target=", binding.target)
    print("App3 available providers:", sorted(str(t) for t in graph.available_providers_for(App3)))
    # Svc is still NOT visible to App3 (no real re-export); SharedModule is a bogus class provider
    results["docs_advice_yields_class_binding"] = (
        binding.token is SharedModule and binding.resolver_kind == "class"
    )
    results["svc_not_reexported"] = Svc not in graph.available_providers_for(App3)
    from bustan.kernel.ioc.container import build_container

    container = build_container(graph)
    inst = container.resolve(SharedModule, module=App3)
    print("resolve(SharedModule) from App3 ->", type(inst).__name__, "(a bare module instance)")
except Exception as exc:  # noqa: BLE001
    print("unexpected:", type(exc).__name__, exc)

print("--- 4. TROUBLESHOOTING.md text ---")
with open("/home/user/bustan/docs/TROUBLESHOOTING.md", encoding="utf-8") as fh:
    lines = fh.read().splitlines()
for i, line in enumerate(lines, 1):
    if "ExportViolationError" in line or "Fix: add the provider" in line:
        print(f"docs/TROUBLESHOOTING.md:{i}: {line}")

print("results:", results)
if (results.get("class_export_rejected") and results.get("class_msg_says_provider")
        and results.get("dyn_export_rejected") and results.get("dyn_msg_has_dataclass_repr")
        and results.get("docs_advice_yields_class_binding") and results.get("svc_not_reexported")):
    print("RESULT: CONFIRMED - module re-export raises a provider-flavoured ExportViolationError "
          "(with full DynamicModule repr), and the documented fix registers the module class as a "
          "class provider without re-exporting anything")
else:
    print("RESULT: REFUTED/PARTIAL - see results")
