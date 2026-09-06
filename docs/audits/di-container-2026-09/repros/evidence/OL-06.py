# ruff: noqa
# Evidence script for finding OL-06 (workflow id F-38) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-38: overrides cannot target DynamicModule registrations via public module_cls.

Checks:
  (a) override_provider(container, CONFIG, 'fake', module_cls=ConfigModule) on a
      graph whose only CONFIG binding is declared by DynamicModule(ConfigModule,...)
      -> ProviderResolutionError 'not registered in ConfigModule'.
  (b) override without module works when unique (so the token IS registered).
  (c) internal ModuleInstanceKey works.
  (d) two registrations -> ambiguity error names 'module_key' (not a real kwarg
      of override_provider/Container.override).
  (e) TestingModuleBuilder.override_provider has no module parameter, and
      compile() fails on the ambiguous token.
"""
from __future__ import annotations

import inspect

import anyio

from bustan import DynamicModule, InjectionToken, Module, create_app_context
from bustan.kernel.module.dynamic import ModuleInstanceKey
from bustan.errors import ProviderResolutionError
from bustan.testing import create_testing_module, override_provider
from bustan.testing.builder import TestingModuleBuilder
from bustan.kernel.ioc.container import Container

CONFIG = InjectionToken("CONFIG")


@Module()
class ConfigModule:
    pass


def register(value: str) -> DynamicModule:
    return DynamicModule(
        module=ConfigModule,
        providers=({"provide": CONFIG, "use_value": value},),
        exports=(CONFIG,),
    )


@Module(imports=[register("prod")])
class AppModule:
    pass


results: dict[str, bool] = {}

ctx = create_app_context(AppModule)
c = ctx.container
print("bindings:", [(str(k[0]), str(k[1])) for k in c.registry.bindings])

# (a)
try:
    with override_provider(c, CONFIG, "fake", module_cls=ConfigModule):
        print("(a) override with module_cls=ConfigModule OK ->", ctx.get(CONFIG))
    results["a_module_cls_rejected"] = False
except ProviderResolutionError as exc:
    print("(a) module_cls=ConfigModule -> ProviderResolutionError:", exc)
    results["a_module_cls_rejected"] = "not registered in ConfigModule" in str(exc)

# (b)
with override_provider(c, CONFIG, "fake"):
    print("(b) override without module ->", ctx.get(CONFIG))
print("(b) cleared ->", ctx.get(CONFIG))

# (c)
key = ModuleInstanceKey(ConfigModule, "0")
with override_provider(c, CONFIG, "fake", module_cls=key):  # type: ignore[arg-type]
    print("(c) override with internal ModuleInstanceKey ->", ctx.get(CONFIG))

# (d)
@Module(imports=[register("a"), register("b")])
class TwoModule:
    pass


ctx2 = create_app_context(TwoModule)
try:
    ctx2.container.override(CONFIG, "fake")
    results["d_ambiguous_msg_names_module_key"] = False
except ProviderResolutionError as exc:
    print("(d) two registrations ->", exc)
    results["d_ambiguous_msg_names_module_key"] = "specify module_key" in str(exc)
print(
    "    real kwarg names: Container.override ->",
    list(inspect.signature(Container.override).parameters),
    "| override_provider ->",
    list(inspect.signature(override_provider).parameters),
)
results["d_module_key_is_not_a_real_kwarg"] = (
    "module_key" not in inspect.signature(Container.override).parameters
    and "module_key" not in inspect.signature(override_provider).parameters
)

# (e)
sig = inspect.signature(TestingModuleBuilder.override_provider)
print("(e) TestingModuleBuilder.override_provider params:", list(sig.parameters))
results["e_builder_has_no_module_param"] = not any(
    p in sig.parameters for p in ("module", "module_cls", "module_key")
)


async def builder_case() -> None:
    try:
        compiled = await (
            create_testing_module(TwoModule).override_provider(CONFIG).use_value("fake").compile()
        )
        print("(e) builder compile OK ->", compiled.get(CONFIG))
        results["e_builder_compile_fails"] = False
    except ProviderResolutionError as exc:
        print("(e) builder compile -> ProviderResolutionError:", exc)
        results["e_builder_compile_fails"] = True


anyio.run(builder_case)

print("results:", results)
if all(results.values()):
    print("CONFIRMED: public module_cls cannot target DynamicModule bindings; ambiguity error names non-existent 'module_key'; builder has no module argument")
else:
    print("REFUTED (some sub-claims false):", {k: v for k, v in results.items() if not v})
