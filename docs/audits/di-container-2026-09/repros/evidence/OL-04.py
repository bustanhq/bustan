# ruff: noqa
# Evidence script for finding OL-04 (workflow id F-41) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-41: provider lifecycle hooks are duck-typed on every cached singleton value."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import anyio

from bustan import Module, create_app_context
from bustan.kernel.errors import LifecycleError

results: list[tuple[str, bool, str]] = []


class Strategy:
    def on_module_init(self) -> None:
        pass


async def case_class_value() -> None:
    @Module(providers=[{"provide": "STRATEGY_CLS", "use_value": Strategy}])
    class M1:
        pass

    ctx = create_app_context(M1)
    try:
        await ctx.init()
        results.append(("use_value=class with instance hook", False, "startup succeeded"))
    except LifecycleError as exc:
        results.append(("use_value=class with instance hook", True, f"LifecycleError: {exc}"))


async def case_magicmock() -> None:
    mock = MagicMock()

    @Module(providers=[{"provide": "MOCK", "use_value": mock}])
    class M2:
        pass

    ctx = create_app_context(M2)
    await ctx.init()
    await ctx.close()
    names = [c[0] for c in mock.mock_calls]
    expected = {"on_module_init", "on_application_bootstrap", "before_application_shutdown",
                "on_application_shutdown", "on_module_destroy"}
    got = set(names)
    results.append(("MagicMock use_value receives all five hooks", expected <= got, f"mock_calls={names}"))

    amock = AsyncMock()

    @Module(providers=[{"provide": "AMOCK", "use_value": amock}])
    class M3:
        pass

    ctx = create_app_context(M3)
    await ctx.init()
    await ctx.close()
    anames = [c[0] for c in amock.mock_calls]
    results.append(("AsyncMock use_value receives all five hooks", expected <= set(anames), f"mock_calls={anames}"))


async def case_shared_value() -> None:
    events: list[str] = []

    class Pool:
        def on_module_init(self) -> None:
            events.append("init")

        def on_module_destroy(self) -> None:
            events.append("destroy")

    pool = Pool()

    @Module(providers=[{"provide": "POOL_A", "use_value": pool}])
    class A:
        pass

    @Module(providers=[{"provide": "POOL_B", "use_value": pool}])
    class B:
        pass

    @Module(imports=[A, B])
    class Root:
        pass

    ctx = create_app_context(Root)
    await ctx.init()
    await ctx.close()
    results.append(("same object under two tokens gets each hook twice",
                    events.count("init") == 2 and events.count("destroy") == 2, f"events={events}"))


async def main() -> None:
    await case_class_value()
    await case_magicmock()
    await case_shared_value()
    for name, confirmed, detail in results:
        print(f"{'CONFIRMED' if confirmed else 'REFUTED':9s} {name}: {detail}")
    print("OVERALL:", "CONFIRMED" if all(c for _, c, _ in results) else "PARTIAL/REFUTED")


anyio.run(main)
