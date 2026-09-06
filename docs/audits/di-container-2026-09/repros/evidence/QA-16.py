# ruff: noqa
# Evidence script for finding QA-16 (workflow id F-84) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-84: tautological / weak tests in the DI suite.

This is a testing-gap finding. The script gathers executable evidence for the
scriptable sub-claims:
  (a) _build_request helper is duplicated N times in tests with drifting signatures
  (b) the lifecycle runner duck-types hooks via getattr (never isinstance against the
      runtime_checkable Protocols that test_hooks.py:26 exercises)
  (c) override_pipe / override_interceptor / override_filter DO work end-to-end, so a
      behavioural test is possible (the current test only inspects a private dict)
  (d) mutation check: swapping module/provider hook order would still satisfy the
      assertion form used at test_hooks.py:116 ('"service:startup" in events')
  (e) the dynamic-module cycle test needs object.__setattr__ on a frozen dataclass
"""
import ast
import dataclasses
import inspect
import re
import subprocess
from pathlib import Path

import anyio

ROOT = Path("/home/user/bustan")
flags: dict[str, bool] = {}

# (a) duplicated helper
out = subprocess.run(
    ["grep", "-rn", "def _build_request", str(ROOT / "tests")], capture_output=True, text=True
).stdout.strip().splitlines()
sigs = {re.sub(r"^.*?:\d+:", "", line).strip() for line in out}
print(f"(a) _build_request definitions: {len(out)} copies, {len(sigs)} distinct signatures")
for s in sorted(sigs):
    print("     ", s)
flags["helper_duplicated_13x"] = len(out) == 13 and len(sigs) >= 4

# (b) runner duck-types; framework never isinstance-checks lifecycle protocols
runner_src = (ROOT / "src/bustan/kernel/lifecycle/runner.py").read_text()
uses_getattr = "getattr(module_instance, hook_name, None)" in runner_src and "getattr(instance, hook_name, None)" in runner_src
src_isinstance = subprocess.run(
    ["grep", "-rn", r"isinstance(.*\(OnModuleInit\|OnApplicationBootstrap\|BeforeApplicationShutdown\|OnApplicationShutdown\|OnModuleDestroy\)", str(ROOT / "src")],
    capture_output=True, text=True,
).stdout.strip()
print(f"(b) runner uses getattr duck-typing: {uses_getattr}; isinstance checks against lifecycle Protocols in src/: {src_isinstance or 'none'}")
flags["protocol_isinstance_unused_by_framework"] = uses_getattr and not src_isinstance

# (c) pipeline overrides work end-to-end
from bustan import (  # noqa: E402
    Controller, ExceptionFilter, ExecutionContext, Get, Interceptor, Module, Param, Pipe,
    UseFilters, UseInterceptors, UsePipes,
)
from bustan.testing import create_testing_module  # noqa: E402


class UpperPipe(Pipe):
    def transform(self, value, metadata=None):
        return str(value).upper()


class ReplacementPipe(Pipe):
    def transform(self, value, metadata=None):
        return "replaced"


class TagInterceptor(Interceptor):
    async def intercept(self, context, next_handler):
        return {"tag": "original", **(await next_handler())}


class ReplacementInterceptor(Interceptor):
    async def intercept(self, context, next_handler):
        return {"tag": "replacement", **(await next_handler())}


class OriginalFilter(ExceptionFilter):
    exception_types = (ValueError,)

    async def catch(self, exc, context: ExecutionContext):
        return {"filter": "original"}


class ReplacementFilter(ExceptionFilter):
    exception_types = (ValueError,)

    async def catch(self, exc, context: ExecutionContext):
        return {"filter": "replacement"}


@UsePipes(UpperPipe)
@UseInterceptors(TagInterceptor)
@UseFilters(OriginalFilter)
@Controller("/p")
class PC:
    @Get("/boom")
    def boom(self) -> dict:
        raise ValueError("boom")

    @Get("/{value}")
    def read(self, value: str = Param("value")) -> dict:
        return {"value": value}


@Module(controllers=[PC])
class AppModule:
    pass


async def e2e() -> None:
    b = create_testing_module(AppModule)
    b.override_pipe(UpperPipe).use_class(ReplacementPipe)
    b.override_interceptor(TagInterceptor).use_class(ReplacementInterceptor)
    b.override_filter(OriginalFilter).use_class(ReplacementFilter)
    compiled = await b.compile()
    try:
        with compiled.create_client() as client:
            r1 = client.get("/p/abc").json()
            r2 = client.get("/p/boom").json()
    finally:
        await compiled.close()
    print(f"(c) overridden pipe+interceptor -> {r1}; overridden filter -> {r2}")
    flags["pipeline_overrides_work_e2e"] = (
        r1 == {"tag": "replacement", "value": "replaced"} and r2 == {"filter": "replacement"}
    )


anyio.run(e2e)

# current test asserts only private dict membership
test_src = (ROOT / "tests/unit/testing/test_testing_builder.py").read_text()
flags["builder_test_asserts_private_dict_only"] = (
    "builder._pipeline_overrides.pipes[DefaultPipe] is not None" in test_src
    and "DefaultPipe" in test_src and "@UsePipes(DefaultPipe" not in test_src
)
print(f"(c) test_testing_builder.py asserts private _pipeline_overrides dict and never attaches DefaultPipe to a route: {flags['builder_test_asserts_private_dict_only']}")

# (d) weak ordering assertion in test_hooks.py
hooks_src = (ROOT / "tests/unit/kernel/lifecycle/test_hooks.py").read_text().splitlines()
line116 = hooks_src[115].strip()
print(f"(d) test_hooks.py:116 = {line116!r}")
# simulate the event list the runner would produce if provider bootstrap ran BEFORE module bootstrap
mutated = ["app:init", "child:init", "service:init", "service:startup", "app:startup", "child:startup",
           "app:before_shutdown:None", "child:before_shutdown:None", "service:before_shutdown:None",
           "app:shutdown", "child:shutdown", "service:shutdown", "child:destroy", "app:destroy", "service:destroy"]
events = mutated
still_passes = (events[:3] == ["app:init", "child:init", "service:init"]
                and "service:startup" in events
                and "service:before_shutdown:None" in events
                and events[-3:] == ["child:destroy", "app:destroy", "service:destroy"])
print(f"(d) mutated order (provider bootstrap before module bootstrap) still satisfies all assertions of that test: {still_passes}")
flags["hooks_test_does_not_pin_bootstrap_order"] = still_passes and line116 == 'assert "service:startup" in events'

# (e) dynamic module cycle needs object.__setattr__ on a frozen dataclass
from bustan.kernel.module.dynamic import DynamicModule  # noqa: E402

params = dataclasses.fields(DynamicModule)
frozen = DynamicModule.__dataclass_params__.frozen
dyn_test = (ROOT / "tests/unit/kernel/module/test_dynamic_modules.py").read_text()
print(f"(e) DynamicModule frozen={frozen}; test uses object.__setattr__: {'object.__setattr__(dynamic_cycle' in dyn_test}")
flags["cycle_test_uses_object_setattr_on_frozen"] = frozen and "object.__setattr__(dynamic_cycle" in dyn_test

print()
for k, v in flags.items():
    print(f"  {'ok ' if v else 'NO '} {k}")
print("RESULT:", "CITATIONS ACCURATE - testing-gap claims hold (not a runtime defect)" if all(flags.values()) else "SOME CLAIMS INACCURATE - see flags")
