# ruff: noqa
# Evidence script for finding MG-10 (workflow id F-52) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-52: @Module coercions accept sets and single dicts and overwrite silently on double decoration.

1. providers={A, B}: accepted; binding order == set iteration order. Run the child N times in fresh
   interpreters (with different PYTHONHASHSEED and allocation patterns) and compare hook order.
2. providers={'provide': TOK, 'use_value': 1}: accepted at decoration; graph build fails with an
   error that names the dict KEY 'provide' as a provider.
3. @Module applied twice: second application overwrites silently.
"""
from __future__ import annotations

import os
import subprocess
import sys

CHILD = "__child__"

if len(sys.argv) > 1 and sys.argv[1] == CHILD:
    # Child: build a module with a set of providers and print on_module_init order.
    import anyio

    from bustan import Injectable, Module
    from bustan.core.module.metadata import get_module_metadata
    from bustan.app.bootstrap import create_app_context

    # allocate a variable amount of garbage first so class addresses (and so hashes) differ
    pad = [object() for _ in range(int(sys.argv[2]))]  # noqa: F841
    order: list[str] = []

    def make(name: str):
        def on_module_init(self):
            order.append(name)

        cls = type(name, (), {"on_module_init": on_module_init})
        return Injectable()(cls)

    names = ["Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Zeta", "Eta", "Theta"]
    classes = [make(n) for n in names]

    @Module(providers=set(classes))
    class SetMod:
        pass

    meta_order = [c.__name__ for c in get_module_metadata(SetMod).providers]

    async def main():
        ctx = create_app_context(SetMod)
        await ctx.init()
        await ctx.close()

    anyio.run(main)
    print(" ".join(meta_order), "|", " ".join(order))
    sys.exit(0)

results: dict[str, object] = {}

print("--- 1. providers as a set: order across interpreter runs ---")
orders: set[str] = set()
for i, pad in enumerate([0, 1, 7, 100, 1000, 5000, 20000, 65536]):
    env = dict(os.environ, PYTHONHASHSEED=str(i * 7919))
    out = subprocess.run(
        [sys.executable, __file__, CHILD, str(pad)],
        capture_output=True, text=True, env=env, cwd="/home/user/bustan",
    )
    if out.returncode != 0:
        print("child failed:", out.stderr[-800:])
        continue
    line = out.stdout.strip().splitlines()[-1]
    print(f"  run {i} (pad={pad}):", line)
    orders.add(line)
print("distinct (metadata order | on_module_init order) observed:", len(orders))
results["set_accepted"] = len(orders) >= 1
results["set_order_varies"] = len(orders) > 1

print("--- 2. single provider dict passed as providers= ---")
from bustan import Injectable, Module  # noqa: E402
from bustan.core.errors import InvalidModuleError, InvalidProviderError  # noqa: E402
from bustan.core.ioc.tokens import InjectionToken  # noqa: E402
from bustan.core.module.graph import build_module_graph  # noqa: E402
from bustan.core.module.metadata import get_module_metadata  # noqa: E402

TOK = InjectionToken("X")
try:
    @Module(providers={"provide": TOK, "use_value": 1})
    class DictMod:
        pass

    print("decoration accepted; metadata.providers =", get_module_metadata(DictMod).providers)
    results["dict_accepted_at_decoration"] = True
    try:
        build_module_graph(DictMod)
        print("graph accepted?!")
        results["dict_graph_error"] = None
    except (InvalidModuleError, InvalidProviderError) as exc:
        print("graph error:", type(exc).__name__, "-", exc)
        results["dict_graph_error"] = str(exc)
        results["dict_error_names_key"] = "provide" in str(exc) and "Mapping" not in str(exc)
except InvalidModuleError as exc:
    print("rejected at decoration (targeted):", exc)
    results["dict_accepted_at_decoration"] = False

print("--- 3. double decoration ---")


@Injectable()
class A:
    pass


@Injectable()
class B:
    pass


try:
    @Module(providers=[A])
    @Module(providers=[B])
    class Double:
        pass

    provs = get_module_metadata(Double).providers
    print("double @Module accepted; providers =", provs)
    results["double_silent"] = provs == (A,)
except InvalidModuleError as exc:
    print("double decoration rejected:", exc)
    results["double_silent"] = False

print("--- 4. (bonus) other odd iterables: generator, dict_keys, frozenset ---")
gen = (c for c in [A, B])


@Module(providers=gen)
class GenMod:
    pass


print("generator ->", get_module_metadata(GenMod).providers)

print("results:", results)
if results.get("set_accepted") and results.get("dict_accepted_at_decoration") \
        and results.get("dict_error_names_key") and results.get("double_silent"):
    tail = ("; set order DID vary between interpreter runs" if results.get("set_order_varies")
            else "; set order did NOT vary in this sample (hash of classes is id-based)")
    print("RESULT: CONFIRMED - set/dict/double-decoration all accepted silently" + tail)
else:
    print("RESULT: REFUTED/PARTIAL - see results")
