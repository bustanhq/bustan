# ruff: noqa
# Evidence script for finding OL-07 (workflow id F-39) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-39: overridden providers get no lifecycle hooks.

Checks:
  (a) TestingModuleBuilder: override_provider(RealDb).use_class(FakeDb), both define
      on_module_init/on_module_destroy. After compile()+close(): which hooks ran?
      Is anything in scope_manager.singletons?
  (b) create_test_app + init/close with a use_value override.
  (c) Override registered AFTER startup (override_provider context manager on a
      running ApplicationContext): does the replaced real instance still get
      shutdown hooks while the replacement gets none?
"""
from __future__ import annotations

import anyio

from bustan import Injectable, Module, create_app_context
from bustan.testing import create_test_app, create_testing_module, override_provider

hook_events: list[str] = []


@Injectable
class RealDb:
    def on_module_init(self) -> None:
        hook_events.append("real:init")

    def on_module_destroy(self) -> None:
        hook_events.append("real:destroy")


class FakeDb:
    def on_module_init(self) -> None:
        hook_events.append("fake:init")

    def on_module_destroy(self) -> None:
        hook_events.append("fake:destroy")


@Module(providers=[RealDb], exports=[RealDb])
class DbModule:
    pass


checks: dict[str, bool] = {}


async def main() -> None:
    print("--- (a) builder use_class override ---")
    compiled = await create_testing_module(DbModule).override_provider(RealDb).use_class(FakeDb).compile()
    got = compiled.get(RealDb)
    print("get(RealDb) ->", type(got).__name__)
    await compiled.close()
    print("hook events:", hook_events)
    print("singletons:", list(compiled.application.container.scope_manager.singletons))
    checks["a_no_hooks_at_all"] = hook_events == [] and isinstance(got, FakeDb)
    checks["a_singletons_empty"] = not compiled.application.container.scope_manager.singletons

    print("--- (b) create_test_app + use_value override, init()/close() ---")
    hook_events.clear()
    fake = FakeDb()
    app = create_test_app(DbModule, provider_overrides={RealDb: fake})
    await app.init()
    await app.close()
    print("hook events:", hook_events)
    checks["b_no_hooks_at_all"] = hook_events == []

    print("--- (c) override registered AFTER startup ---")
    hook_events.clear()
    ctx = create_app_context(DbModule)
    await ctx.init()
    print("after init:", hook_events)
    with override_provider(ctx.container, RealDb, FakeDb()):
        print("get(RealDb) during override ->", type(ctx.get(RealDb)).__name__)
        await ctx.close()
    print("after close inside override:", hook_events)
    checks["c_real_gets_destroy_fake_gets_nothing"] = hook_events == ["real:init", "real:destroy"]


anyio.run(main)
print("checks:", checks)
if all(checks.values()):
    print("CONFIRMED: override replacement never receives lifecycle hooks; not present in scope_manager.singletons; late override leaves real instance receiving shutdown hooks")
else:
    print("REFUTED (some checks false):", {k: v for k, v in checks.items() if not v})
