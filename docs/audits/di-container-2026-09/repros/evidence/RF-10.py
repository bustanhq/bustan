# ruff: noqa
# Evidence script for finding RF-10 (workflow id F-86) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
# F-86: under create_app_context(), ApplicationContext.get pushes the
# ApplicationContext itself as APPLICATION (application.py:60). ModuleRef /
# DiscoveryService only accept an Application (module_ref.py:57-64,
# discovery.py:72-79) and raise a raw TypeError out of DI.
import asyncio

from bustan import Injectable, Module
from bustan.addons.discovery import DiscoveryModule, DiscoveryService
from bustan.addons.module_ref import ModuleRef
from bustan.app.application import Application, ApplicationContext
from bustan.app.bootstrap import create_app_context
from bustan.kernel.errors import ProviderResolutionError


@Injectable()
class UsesModuleRef:
    def __init__(self, ref: ModuleRef) -> None:
        self.ref = ref


@Module(imports=[DiscoveryModule], providers=[UsesModuleRef])
class AppModule:
    pass


ctx = create_app_context(AppModule)
print("context type:", type(ctx).__name__, "| isinstance(ctx, Application) =", isinstance(ctx, Application),
      "| isinstance(ctx, ApplicationContext) =", isinstance(ctx, ApplicationContext))

outcome = {}
for token in (ModuleRef, DiscoveryService, UsesModuleRef):
    try:
        ctx.get(token)
        outcome[token.__name__] = "ok"
        print(token.__name__, "-> OK")
    except ProviderResolutionError as exc:
        outcome[token.__name__] = "ProviderResolutionError"
        print(token.__name__, "-> ProviderResolutionError:", str(exc)[:140])
    except Exception as exc:  # noqa: BLE001
        outcome[token.__name__] = "RAW " + type(exc).__name__
        print(token.__name__, "-> RAW", type(exc).__name__ + ":", str(exc)[:140])

# Also confirm that the eager startup path (ctx.init) hits the same wall for
# a singleton depending on ModuleRef.
async def try_init():
    ctx2 = create_app_context(AppModule)
    try:
        await ctx2.init()
        return "ok"
    except Exception as exc:  # noqa: BLE001
        return f"{type(exc).__name__}: {str(exc)[:100]}"

print("ctx.init() with singleton depending on ModuleRef ->", asyncio.run(try_init()))

# Control: the same lookups under create_app (HTTP runtime).
from bustan import create_app  # noqa: E402

app = create_app(AppModule)
try:
    app.get(ModuleRef)
    app.get(DiscoveryService)
    print("control: create_app(AppModule).get(ModuleRef/DiscoveryService) -> OK")
    control_ok = True
except Exception as exc:  # noqa: BLE001
    print("control failed:", type(exc).__name__, exc)
    control_ok = False

confirmed = (
    outcome["ModuleRef"] == "RAW TypeError"
    and outcome["DiscoveryService"] == "RAW TypeError"
    and control_ok
)
print("F-86 RESULT:", "CONFIRMED" if confirmed else "REFUTED", outcome)
