# ruff: noqa
# Evidence script for finding OL-14 (workflow id F-58) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-58: aggregated shutdown LifecycleError discards the individual exceptions.

BrokenA.on_application_shutdown raises RuntimeError, BrokenB.on_module_destroy raises ValueError.
Expect (per finding): ctx.close() raises a LifecycleError whose __cause__ is None, that is not an
ExceptionGroup, has no .exceptions, and whose traceback does not reach either hook frame.
Also checks the single-failure path keeps __cause__ (so the loss is specific to aggregation).
"""
from __future__ import annotations

import logging
import traceback

import anyio

from bustan import Module, create_app_context
from bustan.errors import LifecycleError

logging.basicConfig(level=logging.DEBUG)


@Module()
class BrokenA:
    def on_application_shutdown(self, signal: str | None) -> None:
        raise RuntimeError("A failed")


@Module()
class BrokenB:
    def on_module_destroy(self) -> None:
        raise ValueError("B failed")


@Module(imports=[BrokenA, BrokenB])
class Root:
    pass


@Module(imports=[BrokenA])
class RootSingle:
    pass


results: dict[str, bool] = {}


async def main() -> None:
    ctx = create_app_context(Root)
    await ctx.init()
    try:
        await ctx.close()
        print("close() did not raise")
        results["raised"] = False
        return
    except LifecycleError as exc:
        results["raised"] = True
        print("aggregated message:", exc)
        print("type:", type(exc).__mro__)
        print("__cause__:", repr(exc.__cause__), "| __context__:", repr(exc.__context__))
        print("isinstance BaseExceptionGroup:", isinstance(exc, BaseExceptionGroup))
        print("has .exceptions:", hasattr(exc, "exceptions"), "| has .errors:", hasattr(exc, "errors"))
        tb_text = "".join(traceback.format_exception(exc))
        print("---- formatted traceback of the raised error ----")
        print(tb_text)
        print("---- end ----")
        results["cause_none"] = exc.__cause__ is None
        results["not_group"] = not isinstance(exc, BaseExceptionGroup)
        results["no_exceptions_attr"] = not hasattr(exc, "exceptions") and not hasattr(exc, "errors")
        # the hook names appear in the message string, so look for the raising source lines
        results["hook_frames_absent"] = (
            'raise RuntimeError("A failed")' not in tb_text
            and 'raise ValueError("B failed")' not in tb_text
        )
        results["original_types_absent"] = "RuntimeError" not in tb_text and "ValueError" not in tb_text

    ctx2 = create_app_context(RootSingle)
    await ctx2.init()
    try:
        await ctx2.close()
    except LifecycleError as exc:
        print("single failure: __cause__ =", repr(exc.__cause__))
        results["single_path_keeps_cause"] = isinstance(exc.__cause__, RuntimeError)


anyio.run(main)
print()
for k, v in results.items():
    print(f"  {k}: {v}")
print("RESULT:", "CONFIRMED" if all(results.values()) else "REFUTED", "- F-58")
