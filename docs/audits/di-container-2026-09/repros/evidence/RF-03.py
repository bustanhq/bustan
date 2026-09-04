# ruff: noqa
# Evidence script for finding RF-03 (workflow id F-11) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-11: inherited __init__ type hints evaluated in the SUBCLASS module globals -> NameError."""
from __future__ import annotations

import os
import sys
import textwrap
from typing import get_type_hints

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.join(HERE, "_gen_f11")
os.makedirs(PKG, exist_ok=True)
open(os.path.join(PKG, "__init__.py"), "w").close()
with open(os.path.join(PKG, "base_mod.py"), "w") as fh:
    fh.write(textwrap.dedent('''
        from __future__ import annotations
        from typing import Annotated
        from bustan import Injectable, Inject
        from bustan.core.ioc.tokens import InjectionToken

        CONFIG = InjectionToken("CONFIG")
        type Alias = dict  # PEP 695 alias, only defined here

        @Injectable
        class Helper:
            pass

        class TokenOnlyBase:
            def __init__(self, helper: Helper) -> None:
                self.helper = helper

        class MarkerBase:
            def __init__(self, helper: Helper, cfg: Annotated[object, Inject(CONFIG)]) -> None:
                self.helper = helper
                self.cfg = cfg

        class AliasBase:
            def __init__(self, value: Annotated[Alias, Inject(CONFIG)]) -> None:
                self.value = value
    '''))
with open(os.path.join(PKG, "child_mod.py"), "w") as fh:
    fh.write(textwrap.dedent('''
        from __future__ import annotations
        from bustan import Injectable
        from .base_mod import TokenOnlyBase, MarkerBase, AliasBase  # Helper/Inject/CONFIG/Alias NOT imported here

        @Injectable
        class TokenOnlyChild(TokenOnlyBase):
            pass

        @Injectable
        class MarkerChild(MarkerBase):
            pass

        @Injectable
        class AliasChild(AliasBase):
            pass
    '''))

sys.path.insert(0, HERE)
from _gen_f11 import base_mod, child_mod  # noqa: E402

from bustan import Module, create_app_context  # noqa: E402
from bustan.core.errors import ProviderResolutionError  # noqa: E402


def attempt(cls: type) -> str:
    @Module(providers=[base_mod.Helper, cls, {"provide": base_mod.CONFIG, "use_value": {"k": 1}}])
    class AppModule:
        pass

    try:
        create_app_context(AppModule).get(cls)
        return "resolved"
    except ProviderResolutionError as exc:
        return f"FAILED: {exc}"


token_only = attempt(child_mod.TokenOnlyChild)
marker = attempt(child_mod.MarkerChild)
alias = attempt(child_mod.AliasChild)
print("TokenOnlyChild (annotation names are visible tokens, rescued by synthesized namespace):", token_only)
print("MarkerChild   (Inject/CONFIG imported only in base module):", marker)
print("AliasChild    (PEP 695 alias defined only in base module):", alias)

# control: evaluating with the constructor's own __globals__ works
ctrl = get_type_hints(child_mod.MarkerChild.__init__, include_extras=True)
print("control get_type_hints(MarkerChild.__init__) with function globals ->", {k: str(v) for k, v in ctrl.items()})
print("MarkerChild.__init__.__globals__ is base_mod globals:", child_mod.MarkerChild.__init__.__globals__ is vars(base_mod))
print("resolver uses sys.modules[MarkerChild.__module__] =", child_mod.MarkerChild.__module__)

print()
if token_only == "resolved" and "'Inject' is not defined" in marker and "'Alias' is not defined" in alias:
    print("RESULT: CONFIRMED - inherited __init__ annotations are evaluated in the subclass module; marker/alias names from the base module raise NameError")
else:
    print("RESULT: NOT FULLY REPRODUCED")
