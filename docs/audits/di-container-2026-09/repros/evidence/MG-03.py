# ruff: noqa
# Evidence script for finding MG-03 (workflow id F-29) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-29: ModuleGraph.available_providers vs Registry.module_visibility disagree.

Claim A: a token exported by an is_global module is resolvable from a consumer
         but absent from ModuleGraph.available_providers_for(consumer).
Claim B: a module that can resolve the global token cannot export it
         (ExportViolationError), because _validate_exports uses the graph view.
Claim C (F-08 cross-ref): a re-exported token is present in available_providers
         but unresolvable through the registry.
"""
from bustan import Injectable, Module
from bustan.app.bootstrap import create_app_context
from bustan.core.module.graph import build_module_graph
from bustan.core.errors import ExportViolationError, ProviderResolutionError

results = []


@Injectable()
class GlobalSvc:
    pass


@Module(providers=[GlobalSvc], exports=[GlobalSvc], is_global=True)
class GlobalModule:
    pass


@Module()
class Consumer:
    pass


@Module(imports=[GlobalModule, Consumer])
class Root:
    pass


# Claim A
ctx = create_app_context(Root)
graph = ctx.container.module_graph
in_graph_view = GlobalSvc in graph.available_providers_for(Consumer)
in_registry_view = GlobalSvc in ctx.container.registry.module_visibility[Consumer]
try:
    resolved = ctx.container.resolve(GlobalSvc, module=Consumer)
    resolve_ok = isinstance(resolved, GlobalSvc)
except ProviderResolutionError as exc:
    resolve_ok = False
    print("resolve error:", exc)
print(f"A: graph.available_providers_for(Consumer) has GlobalSvc = {in_graph_view}")
print(f"A: registry.module_visibility[Consumer] has GlobalSvc  = {in_registry_view}")
print(f"A: container.resolve(GlobalSvc, module=Consumer) works   = {resolve_ok}")
claim_a = (not in_graph_view) and in_registry_view and resolve_ok
results.append(("A global token resolvable but absent from graph view", claim_a))


# Claim B: Facade tries to export the global token it can resolve
@Module(exports=[GlobalSvc])
class Facade:
    pass


@Module(imports=[GlobalModule, Facade])
class Root2:
    pass


try:
    build_module_graph(Root2)
    claim_b = False
    print("B: build_module_graph(Root2) succeeded (no ExportViolationError)")
except ExportViolationError as exc:
    claim_b = True
    print(f"B: ExportViolationError: {exc}")
results.append(("B module cannot export a globally visible token it can resolve", claim_b))


# Claim C: re-export shows in graph view but not resolvable
@Injectable()
class Inner:
    pass


@Module(providers=[Inner], exports=[Inner])
class InnerModule:
    pass


@Module(imports=[InnerModule], exports=[Inner])
class Middle:
    pass


@Module(imports=[Middle])
class Outer:
    pass


@Module(imports=[Outer])
class Root3:
    pass


ctx3 = create_app_context(Root3)
g3 = ctx3.container.module_graph
in_graph_c = Inner in g3.available_providers_for(Outer)
in_registry_c = Inner in ctx3.container.registry.module_visibility[Outer]
try:
    ctx3.container.resolve(Inner, module=Outer)
    resolve_c = True
except ProviderResolutionError as exc:
    resolve_c = False
    print(f"C: resolve error: {exc}")
print(f"C: graph.available_providers_for(Outer) has Inner = {in_graph_c}")
print(f"C: registry.module_visibility[Outer] has Inner  = {in_registry_c}")
print(f"C: container.resolve(Inner, module=Outer) works  = {resolve_c}")
claim_c = in_graph_c and not in_registry_c and not resolve_c
results.append(("C re-exported token in graph view but unresolvable", claim_c))

print()
for label, ok in results:
    print(("CONFIRMED " if ok else "REFUTED   ") + label)
print("OVERALL:", "PASS (defect demonstrated)" if all(ok for _, ok in results) else "PARTIAL/FAIL")
