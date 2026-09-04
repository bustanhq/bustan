# ruff: noqa
# Evidence script for finding OL-01 (workflow id F-14) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-14: override()/clear_override() only invalidate controller singletons; provider singletons keep the
old dependency, and a singleton first built during an override keeps the fake after the block exits."""
from __future__ import annotations

from typing import Any, cast

from starlette.testclient import TestClient

from bustan import Controller, Get, Injectable, Module, create_app, create_app_context
from bustan.testing import override_provider


@Injectable
class GreetingService:
    def greet(self) -> str:
        return "production"


class FakeGreetingService:
    def greet(self) -> str:
        return "fake"


@Injectable
class WelcomeService:  # singleton depending on GreetingService
    def __init__(self, greeting: GreetingService) -> None:
        self.greeting = greeting

    def welcome(self) -> str:
        return "welcome:" + self.greeting.greet()


@Controller("/hello")
class HelloController:
    def __init__(self, greeting: GreetingService, welcome: WelcomeService) -> None:
        self.greeting = greeting
        self.welcome = welcome

    @Get("/direct")
    def direct(self) -> dict[str, str]:
        return {"msg": self.greeting.greet()}

    @Get("/transitive")
    def transitive(self) -> dict[str, str]:
        return {"msg": self.welcome.welcome()}


@Module(controllers=[HelloController], providers=[GreetingService, WelcomeService])
class AppModule:
    pass


checks: dict[str, bool] = {}

print("-- Scenario A: README override_provider inside `with TestClient(app)` (lifespan eagerly built singletons)")
app = create_app(AppModule)
with TestClient(cast(Any, app)) as client:
    with override_provider(app, GreetingService, FakeGreetingService()):
        direct = client.get("/hello/direct").json()["msg"]
        transitive = client.get("/hello/transitive").json()["msg"]
        print("   inside override: /hello/direct ->", direct, "| /hello/transitive ->", transitive)
    checks["A_direct_is_fake"] = direct == "fake"
    checks["A_transitive_stale_production"] = transitive == "welcome:production"
    print("   singleton cache size (provider singletons untouched by override):",
          len(app.container.scope_manager.singletons))

print("-- Scenario B: no lifespan; singleton first built DURING the override keeps the fake after the block")
ctx = create_app_context(AppModule)
# note: override_provider accepts Container/Application/Starlette, not a bare ApplicationContext
with override_provider(ctx.container, GreetingService, FakeGreetingService()):
    inside = ctx.get(WelcomeService).welcome()
after = ctx.get(WelcomeService).welcome()
direct_after = ctx.get(GreetingService).greet()
print("   inside override: WelcomeService.welcome() ->", inside)
print("   after override : WelcomeService.welcome() ->", after, "| GreetingService.greet() ->", direct_after)
checks["B_inside_is_fake"] = inside == "welcome:fake"
checks["B_fake_outlives_override"] = after == "welcome:fake" and direct_after == "production"

print("-- Scenario C: durable/request caches also untouched? (controller singleton IS cleared: check the API says so)")
print("   Container.override clears only controller_singletons; provider singletons after override:",
      list(type(v).__name__ for v in ctx.container.scope_manager.singletons.values()))

print()
for k, v in checks.items():
    print(f"   {k}: {v}")
confirmed = all(checks.values())
print("F-14", "CONFIRMED" if confirmed else "REFUTED")
