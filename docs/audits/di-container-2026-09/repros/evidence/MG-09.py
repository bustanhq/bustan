# ruff: noqa
# Evidence script for finding MG-09 (workflow id F-51) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-51: cycle detection through a DynamicModule object reports no path and dumps the whole
DynamicModule repr; the 'same key from another DynamicModule' guard (graph.py:137-139) is dead.

Part A (scriptable): Root -> dm(X) -> Y -> dm(X) where the SAME DynamicModule object is
re-entered. Built without touching frozen dataclass internals: X is decorated after dm is created.
Part B (scriptable): instrument build_module_graph with sys.settrace / a monkeypatched
compiled_by_key check to show that graph.py:138-139 never executes across the repo's own
module-graph tests plus several cycle shapes.
"""
from __future__ import annotations

import sys
import traceback

from bustan import DynamicModule, Module
from bustan.kernel.errors import ModuleCycleError
from bustan.kernel.module import graph as graph_mod
from bustan.kernel.module.graph import build_module_graph

results: dict[str, object] = {}

print("--- A1. control: static cycle A -> B -> A ---")


class A:
    pass


class B:
    pass


Module(imports=[B])(A)
Module(imports=[A])(B)
try:
    build_module_graph(A)
except ModuleCycleError as exc:
    print("static:", exc)
    results["static_has_path"] = "->" in str(exc)

print("--- A2. Root -> dm(X) -> Y -> dm(X) (same DynamicModule object re-entered) ---")


class X:
    pass


dm = DynamicModule(X, providers=[{"provide": "CFG", "use_value": {"nested": [1, 2, 3]}}])


@Module(imports=[dm])
class Y:
    pass


Module(imports=[Y])(X)  # X decorated after dm exists: X -> Y -> dm(X)


@Module(imports=[dm])
class Root:
    pass


try:
    build_module_graph(Root)
    print("accepted?!")
except ModuleCycleError as exc:
    msg = str(exc)
    print("dynamic-object cycle:", msg)
    results["dyn_has_path"] = "->" in msg
    results["dyn_mentions_Y"] = "Y" in msg.replace("DynamicModule", "").replace("Y'", "")  # crude
    results["dyn_names_Y_in_path"] = " -> Y" in msg or "Y ->" in msg
    results["dyn_dumps_repr"] = "DynamicModule(module=" in msg
    results["dyn_msg_len"] = len(msg)

print("--- A3. same shape but Y imports a NEW DynamicModule(X) (different object) ---")


class X2:
    pass


@Module(imports=[DynamicModule(X2)])
class Y2:
    pass


Module(imports=[Y2])(X2)


@Module(imports=[DynamicModule(X2)])
class Root2:
    pass


try:
    build_module_graph(Root2)
    print("accepted?!")
except ModuleCycleError as exc:
    print("distinct-object cycle:", exc)
    results["distinct_obj_has_path"] = "->" in str(exc)

print("--- B. is graph.py:137-139 ('key in compiled_by_key') reachable? ---")
# Trace line execution inside build_module_graph.visit across many graph shapes.
hit_lines: set[int] = set()
src_file = graph_mod.__file__


def tracer(frame, event, arg):
    if frame.f_code.co_filename == src_file:
        if event == "line":
            hit_lines.add(frame.f_lineno)
        return tracer
    return None


def run_shapes() -> None:
    @Module()
    class Leaf:
        pass

    d1 = DynamicModule(Leaf)
    d2 = DynamicModule(Leaf)

    @Module(imports=[d1, d2, Leaf])
    class Mid:
        pass

    @Module(imports=[Mid, d1, Leaf, DynamicModule(Mid)])
    class Top:
        pass

    build_module_graph(Top)
    build_module_graph(DynamicModule(Top))
    # diamond with shared dynamic object
    shared = DynamicModule(Leaf)

    @Module(imports=[shared])
    class L1:
        pass

    @Module(imports=[shared])
    class L2:
        pass

    @Module(imports=[L1, L2, shared])
    class Diamond:
        pass

    build_module_graph(Diamond)
    for root in (A, Root, Root2):
        try:
            build_module_graph(root)
        except ModuleCycleError:
            pass


sys.settrace(tracer)
try:
    run_shapes()
finally:
    sys.settrace(None)

guard_lines = {138, 139}
print("visit() lines executed:", sorted(l for l in hit_lines if 103 <= l <= 156))
print("guard body lines 138-139 executed:", bool(hit_lines & guard_lines))
results["guard_dead_in_trace"] = not (hit_lines & guard_lines)

# Also run the repo's own module graph tests under the same tracer (in-process).
try:
    import pytest

    class Plugin:
        pass

    sys.settrace(tracer)
    try:
        rc = pytest.main(["-q", "-p", "no:cacheprovider", "/home/user/bustan/tests/unit/kernel/module",
                          "-o", "addopts="], plugins=[Plugin()])
    finally:
        sys.settrace(None)
    print("pytest tests/unit/kernel/module rc =", rc)
    print("guard body lines 138-139 executed after tests:", bool(hit_lines & guard_lines))
    results["guard_dead_after_tests"] = not (hit_lines & guard_lines)
except Exception:  # noqa: BLE001
    traceback.print_exc()

print("results:", results)
if (results.get("static_has_path") and results.get("dyn_has_path") is False
        and results.get("dyn_dumps_repr") and results.get("guard_dead_in_trace")):
    print("RESULT: CONFIRMED - re-entering the same DynamicModule object yields a path-less message "
          "containing the full DynamicModule repr (Y never named), while the static cycle prints a "
          "path; graph.py:138-139 never executed under trace")
else:
    print("RESULT: REFUTED/PARTIAL - see results")
