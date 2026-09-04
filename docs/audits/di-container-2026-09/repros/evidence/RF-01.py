# ruff: noqa
# Evidence script for finding RF-01 (workflow id F-12) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-12: synthesized annotation namespace shadows lexical scope for same-named token classes."""
from __future__ import annotations

import os
import sys
import textwrap

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.join(HERE, "_gen_f12")
os.makedirs(PKG, exist_ok=True)
open(os.path.join(PKG, "__init__.py"), "w").close()
with open(os.path.join(PKG, "dup_a.py"), "w") as fh:
    fh.write(textwrap.dedent('''
        from __future__ import annotations
        from bustan import Injectable, Module

        @Injectable
        class Repo:
            name = "dup_a.Repo"

        @Module(providers=[Repo], exports=[Repo])
        class AModule: ...
    '''))
with open(os.path.join(PKG, "dup_b.py"), "w") as fh:
    fh.write(textwrap.dedent('''
        from __future__ import annotations
        from bustan import Injectable, Module

        @Injectable
        class Repo:
            name = "dup_b.Repo"

        @Injectable
        class Consumer:
            def __init__(self, repo: Repo) -> None:  # lexically dup_b.Repo
                self.repo = repo

        @Module(providers=[Repo], exports=[Repo])
        class BModule: ...
    '''))

sys.path.insert(0, HERE)
from _gen_f12 import dup_a, dup_b  # noqa: E402

from bustan import Module, create_app_context  # noqa: E402

EXPECTED = "dup_b.Repo"
observations: list[tuple[str, str]] = []


# Case 1: dup_a.Repo declared locally, dup_b.Repo arrives via import
@Module(imports=[dup_b.BModule], providers=[dup_a.Repo, dup_b.Consumer])
class App1:
    pass


observations.append(("local dup_a.Repo + import BModule", create_app_context(App1).get(dup_b.Consumer).repo.name))


# Case 2/3: both Repos via imports, order swapped
@Module(imports=[dup_b.BModule, dup_a.AModule], providers=[dup_b.Consumer])
class App2:
    pass


@Module(imports=[dup_a.AModule, dup_b.BModule], providers=[dup_b.Consumer])
class App3:
    pass


observations.append(("imports=[BModule, AModule]", create_app_context(App2).get(dup_b.Consumer).repo.name))
observations.append(("imports=[AModule, BModule]", create_app_context(App3).get(dup_b.Consumer).repo.name))


# Control: only dup_b.Repo visible
@Module(imports=[dup_b.BModule], providers=[dup_b.Consumer])
class App4:
    pass


observations.append(("control imports=[BModule] only", create_app_context(App4).get(dup_b.Consumer).repo.name))

misbound = []
for label, got in observations:
    flag = "ok" if got == EXPECTED else "MISBOUND"
    if flag == "MISBOUND":
        misbound.append(label)
    print(f"[{flag}] {label}: Consumer.repo is {got} (lexical meaning: {EXPECTED})")

print()
if observations[0][1] == "dup_a.Repo" and observations[2][1] == "dup_a.Repo" and observations[1][1] == EXPECTED and observations[3][1] == EXPECTED:
    print("RESULT: CONFIRMED - string annotation 'Repo' resolved to the first same-named visible token, overriding lexical scope; import order flips the injected class, no diagnostic")
else:
    print("RESULT: NOT FULLY REPRODUCED", observations)
