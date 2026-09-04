# ruff: noqa
# Evidence script for finding OL-16 (workflow id F-91) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
# F-91: the lifecycle 'signal' argument is never supplied by any caller, so
# shutdown hooks always receive None (both through ApplicationContext.close()
# and the Starlette lifespan).
import asyncio
import subprocess
from typing import Any, cast

from starlette.testclient import TestClient

from bustan import Injectable, Module, create_app
from bustan.app.bootstrap import create_app_context

seen: list[object] = []
SENTINEL = object()


@Injectable()
class Pool:
    def before_application_shutdown(self, signal: str | None) -> None:
        seen.append(("provider.before", signal if signal is not None else SENTINEL))

    def on_application_shutdown(self, signal: str | None) -> None:
        seen.append(("provider.on", signal if signal is not None else SENTINEL))


@Module(providers=[Pool])
class AppModule:
    def on_application_shutdown(self, signal: str | None) -> None:
        seen.append(("module.on", signal if signal is not None else SENTINEL))


async def via_context() -> None:
    ctx = create_app_context(AppModule)
    await ctx.init()
    await ctx.close()


asyncio.run(via_context())
ctx_seen = list(seen)
seen.clear()

with TestClient(cast(Any, create_app(AppModule))):
    pass
lifespan_seen = list(seen)

fmt = lambda s: [(n, "None" if v is SENTINEL else repr(v)) for n, v in s]  # noqa: E731
print("ApplicationContext.close() ->", fmt(ctx_seen))
print("Starlette lifespan shutdown ->", fmt(lifespan_seen))

grep = subprocess.run(
    ["grep", "-rn", r"shutdown(", "/home/user/bustan/src/bustan"],
    capture_output=True, text=True,
).stdout.strip().splitlines()
print("callers of shutdown( in src/bustan:")
for line in grep:
    print("   ", line)
callers_pass_signal = [line for line in grep if "signal=" in line and "def shutdown" not in line]
print("callers passing signal=:", callers_pass_signal or "none")

all_none = ctx_seen and lifespan_seen and all(v is SENTINEL for _, v in ctx_seen + lifespan_seen)
ok = bool(all_none) and not callers_pass_signal
print("RESULT:", "PASS (hooks always receive None)" if ok else "FAIL")
