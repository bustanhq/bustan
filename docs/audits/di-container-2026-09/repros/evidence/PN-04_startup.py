# ruff: noqa
# Evidence script for finding PN-04 (workflow id F-32) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-32 supplement: do bad use_class/use_factory targets surface at startup
(eager singleton instantiation) or only at first request-time resolution?"""
import asyncio, traceback
from bustan import Module
from bustan.app.bootstrap import create_app_context
from bustan.kernel.errors import BustanError


class Svc:
    pass


@Module(providers=[{"provide": "inst", "use_class": Svc()}])
class RootSingleton:
    pass


@Module(providers=[{"provide": "fac", "use_factory": 42, "scope": "transient"}])
class RootTransient:
    pass


async def main():
    for root in (RootSingleton, RootTransient):
        ctx = create_app_context(root)
        try:
            await ctx.init()
            print(f"{root.__name__}: startup OK (bad target NOT caught at boot)")
        except Exception as exc:  # noqa: BLE001
            print(f"{root.__name__}: startup raised {type(exc).__name__}: {exc} (BustanError={isinstance(exc, BustanError)})")
        # where does AttributeError come from?
        try:
            ctx.get("inst" if root is RootSingleton else "fac")
        except Exception:
            tb = traceback.format_exc().splitlines()
            print("   innermost frames:", [l.strip() for l in tb if "resolver.py" in l][-2:])

asyncio.run(main())
