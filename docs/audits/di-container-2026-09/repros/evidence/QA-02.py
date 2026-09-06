# ruff: noqa
# Evidence script for finding QA-02 (workflow id F-45) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
# Left naming the pre-rename package tree, on purpose. The packages were renamed after
# this ran - core to kernel, platform/http to runtime, logger to observability, config
# to configuration - but the only file this script measures, src/bustan/core/ioc/resolver.py,
# was deleted rather than renamed and has no successor at any path. Renaming the names
# around it would not let it run, and would claim it had measured a tree it never saw.
"""F-45: Resolver size, sync/async twin pairs, similarity, parameter counts, and drift facts.

Measures src/bustan/core/ioc/resolver.py with ast/difflib and checks the concrete drift claims:
  - resolve() caches via a closure/store under a threading lock, resolve_async() goes through _cache_instance
  - _binding_requires_async is called in resolve() but nowhere in resolve_async()
"""
from __future__ import annotations

import ast
import difflib
import pathlib

SRC = pathlib.Path("/home/user/bustan/src/bustan/core/ioc/resolver.py")
text = SRC.read_text()
lines = text.splitlines()
tree = ast.parse(text)

resolver_cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Resolver")
methods = [n for n in resolver_cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
cls_lines = resolver_cls.end_lineno - resolver_cls.lineno + 1
print(f"file lines={len(lines)} Resolver class lines={cls_lines} (L{resolver_cls.lineno}-L{resolver_cls.end_lineno}) methods={len(methods)}")

by_name = {m.name: m for m in methods}


def body_src(fn: ast.AST) -> list[str]:
    out = []
    for ln in lines[fn.lineno - 1 : fn.end_lineno]:
        s = ln.strip()
        s = s.replace("await ", "").replace("async ", "").replace("_async", "")
        out.append(s)
    return out


pairs = [
    ("resolve", "resolve_async"),
    ("_construct_binding", "_construct_binding_async"),
    ("_resolve_binding", "_resolve_binding_async"),
    ("instantiate_class", "instantiate_class_async"),
    ("call_factory", "call_factory_async"),
    ("_resolve_constructor_dependencies", "_resolve_constructor_dependencies_async"),
    ("_resolve_declared_dependency", "_resolve_declared_dependency_async"),
    ("_shared_instance_slot", "_shared_async_construction_lock"),
]
total = 0
for a, b in pairs:
    fa, fb = by_name[a], by_name[b]
    la = fa.end_lineno - fa.lineno + 1
    lb = fb.end_lineno - fb.lineno + 1
    total += la + lb
    ratio = difflib.SequenceMatcher(None, body_src(fa), body_src(fb)).ratio()
    print(f"pair {a}(L{fa.lineno},{la}) / {b}(L{fb.lineno},{lb}) similarity={ratio:.2f}")
print(f"total twin lines={total}")

wide = []
for m in methods:
    n = len(m.args.args) + len(m.args.kwonlyargs) - 1  # minus self
    if n >= 6:
        wide.append((m.name, n, m.lineno))
print("methods with >=6 parameters:", wide)

# Drift facts
def calls_in(fn: ast.AST) -> set[str]:
    names = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            names.add(node.func.attr)
    return names

sync_calls = calls_in(by_name["resolve"])
async_calls = calls_in(by_name["resolve_async"])
print("resolve() calls _binding_requires_async:", "_binding_requires_async" in sync_calls)
print("resolve_async() calls _binding_requires_async:", "_binding_requires_async" in async_calls)
print("resolve() calls _cache_instance:", "_cache_instance" in sync_calls, "| uses _shared_instance_slot store():", "_shared_instance_slot" in sync_calls)
print("resolve_async() calls _cache_instance:", "_cache_instance" in async_calls, "| calls _shared_async_construction_lock:", "_shared_async_construction_lock" in async_calls)

drift_ok = (
    "_binding_requires_async" in sync_calls
    and "_binding_requires_async" not in async_calls
    and "_cache_instance" in async_calls
    and "_shared_instance_slot" in sync_calls
)
print("PASS: claimed twin pairs and drift are present in the source" if drift_ok and len(pairs) == 8 else "FAIL: claims do not match source")
