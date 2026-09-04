# ruff: noqa
# Evidence script for finding OL-10 (workflow id F-43) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-43: iscoroutinefunction predicate vs isawaitable(result) at call time."""
import asyncio
import gc
import inspect
import warnings

from bustan import Module, create_app_context
from bustan.core.errors import ProviderResolutionError

TOKEN = object()


class AsyncFactory:
    async def __call__(self) -> str:
        return "built"


async def plain_async_factory() -> str:
    return "built"


def sync_factory_returning_coroutine() -> object:
    return plain_async_factory()


def label(f):
    return f.__name__ if inspect.isfunction(f) else type(f).__name__


print("iscoroutinefunction(AsyncFactory()) =", inspect.iscoroutinefunction(AsyncFactory()))
print("iscoroutinefunction(sync_factory_returning_coroutine) =", inspect.iscoroutinefunction(sync_factory_returning_coroutine))
print("iscoroutinefunction(plain_async_factory) =", inspect.iscoroutinefunction(plain_async_factory))

outcomes: dict[str, str] = {}


async def main() -> None:
    for factory in (AsyncFactory(), sync_factory_returning_coroutine, plain_async_factory):
        @Module(providers=[{"provide": TOKEN, "use_factory": factory}])
        class AppModule:
            pass

        ctx = create_app_context(AppModule)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            try:
                await ctx.init()
                warmed = TOKEN in {k[1] for k in ctx.container.scope_manager.singletons}
                value = ctx.get(TOKEN)
                outcomes[label(factory)] = f"init OK; warmed={warmed}; get -> {value!r}"
            except ProviderResolutionError as exc:
                outcomes[label(factory)] = f"init OK; ProviderResolutionError: {exc}"
            gc.collect()
            never_awaited = [str(w.message) for w in caught if "never awaited" in str(w.message)]
        outcomes[label(factory)] += f"; never-awaited warnings={never_awaited}"

    for k, v in outcomes.items():
        print(f"  {k}: {v}")

    bad_async_call = "ProviderResolutionError" in outcomes["AsyncFactory"] and outcomes["AsyncFactory"].count("never awaited") >= 1
    bad_sync_coro = "ProviderResolutionError" in outcomes["sync_factory_returning_coroutine"]
    good_plain = "get -> 'built'" in outcomes["plain_async_factory"]
    print("OVERALL:", "CONFIRMED" if (bad_async_call and bad_sync_coro and good_plain) else "REFUTED")


asyncio.run(main())
