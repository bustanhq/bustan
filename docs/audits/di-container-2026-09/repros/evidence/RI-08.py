# ruff: noqa
# Evidence script for finding RI-08 (workflow id F-19) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-19: INQUIRER in a singleton records only the first inquirer; eager startup
depends on provider declaration order; factory-built classes see the factory consumer."""
from __future__ import annotations

from typing import Annotated, Any, cast

import anyio

from bustan import INQUIRER, Inject, Injectable, Module, Scope, create_app_context
from bustan.kernel.ioc.container import build_container
from bustan.kernel.module.graph import build_module_graph
from bustan.errors import LifecycleError, ProviderResolutionError


@Injectable  # SINGLETON
class Logger:
    def __init__(self, inquirer: Annotated[object, Inject(INQUIRER)]) -> None:
        self.inquirer = inquirer


@Injectable
class Billing:
    def __init__(self, logger: Logger) -> None:
        self.logger = logger


@Injectable
class Shipping:
    def __init__(self, logger: Logger) -> None:
        self.logger = logger


@Module(providers=[Billing, Shipping, Logger], exports=[Billing, Shipping])
class SharedModule:
    pass


container = build_container(build_module_graph(SharedModule))
billing = cast(Any, container.resolve(Billing, module=SharedModule))
shipping = cast(Any, container.resolve(Shipping, module=SharedModule))
print("[1] singleton Logger: Billing sees", billing.logger.inquirer.__name__,
      "| Shipping sees", shipping.logger.inquirer.__name__,
      "| same Logger instance:", billing.logger is shipping.logger)
wrong_inquirer = shipping.logger.inquirer is Billing


# Transient variant
@Injectable(scope=Scope.TRANSIENT)
class TLogger:
    def __init__(self, inquirer: Annotated[object, Inject(INQUIRER)]) -> None:
        self.inquirer = inquirer


@Injectable
class TBilling:
    def __init__(self, logger: TLogger) -> None:
        self.logger = logger


@Injectable
class TShipping:
    def __init__(self, logger: TLogger) -> None:
        self.logger = logger


@Module(providers=[TBilling, TShipping, TLogger], exports=[TBilling, TShipping])
class TransientModule:
    pass


c2 = build_container(build_module_graph(TransientModule))
tb = cast(Any, c2.resolve(TBilling, module=TransientModule))
ts = cast(Any, c2.resolve(TShipping, module=TransientModule))
print("[2] transient TLogger: TBilling sees", tb.logger.inquirer.__name__, "| TShipping sees", ts.logger.inquirer.__name__)
transient_ok = tb.logger.inquirer is TBilling and ts.logger.inquirer is TShipping


# Startup order dependence
@Injectable
class ServiceA:
    def __init__(self, logger: Logger) -> None:
        self.logger = logger


@Module(providers=[Logger, ServiceA], exports=[ServiceA])
class LoggerFirst:
    pass


@Module(providers=[ServiceA, Logger], exports=[ServiceA])
class ConsumerFirst:
    pass


async def init_case(module: type[object]) -> str:
    ctx = create_app_context(module)
    try:
        await ctx.init()
        return "ok"
    except LifecycleError as exc:
        return f"LifecycleError: {exc}"
    except ProviderResolutionError as exc:
        return f"ProviderResolutionError: {exc}"


r_logger_first = anyio.run(init_case, LoggerFirst)
r_consumer_first = anyio.run(init_case, ConsumerFirst)
print("[3] providers=[Logger, ServiceA] init() ->", r_logger_first[:120])
print("[4] providers=[ServiceA, Logger] init() ->", r_consumer_first[:120])
order_dependent = r_logger_first.startswith("ProviderResolutionError") and r_consumer_first == "ok"


# Factory inject path: call_factory pushes no construction frame
@Injectable(scope=Scope.TRANSIENT)
class Probe:
    def __init__(self, inquirer: Annotated[object, Inject(INQUIRER)]) -> None:
        self.inquirer = inquirer


class Built:
    def __init__(self, probe: Probe) -> None:
        self.probe = probe


def make_built(probe: Probe) -> Built:
    return Built(probe)


@Injectable
class FactoryConsumer:
    def __init__(self, built: Annotated[object, Inject("BUILT")]) -> None:
        self.built = built


@Module(
    providers=[Probe, {"provide": "BUILT", "use_factory": make_built, "inject": (Probe,)}, FactoryConsumer],
    exports=[FactoryConsumer],
)
class FactoryModule:
    pass


c3 = build_container(build_module_graph(FactoryModule))
fc = cast(Any, c3.resolve(FactoryConsumer, module=FactoryModule))
print("[5] Probe built through factory inject: INQUIRER ->", getattr(fc.built.probe.inquirer, "__name__", fc.built.probe.inquirer))
factory_sees_consumer = fc.built.probe.inquirer is FactoryConsumer

try:
    c3.resolve("BUILT", module=FactoryModule)
    print("[6] top-level resolve of factory 'BUILT' -> ok (no frame pushed?)")
    top_level_factory = "ok"
except ProviderResolutionError as exc:
    print("[6] top-level resolve of factory 'BUILT' ->", str(exc)[:100])
    top_level_factory = "error"

print()
print("singleton INQUIRER shared, Shipping sees Billing:", wrong_inquirer)
print("transient variant correct:", transient_ok)
print("startup succeeds/fails depending on declaration order:", order_dependent)
print("factory-injected class sees the factory's consumer (not the factory):", factory_sees_consumer)
print("F-19", "CONFIRMED" if (wrong_inquirer and order_dependent) else "REFUTED")
