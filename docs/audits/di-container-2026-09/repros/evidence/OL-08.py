# ruff: noqa
# Evidence script for finding OL-08 (workflow id F-40) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-40: TestingModuleBuilder resolves use_class/use_factory replacements from ROOT.

UsersModule(providers=[Db, UserService], exports=[UserService])  # Db NOT exported
AppModule(imports=[UsersModule])
create_testing_module(AppModule).override_provider(UserService).use_class(FakeUserService)
  -> expected per finding: ProviderResolutionError '... not available to AppModule'.
Control: the same replacement instantiated with module=UsersModule (declaring module) works.
"""
from __future__ import annotations

import anyio

from bustan import Injectable, Module
from bustan.errors import ProviderResolutionError
from bustan.testing import create_testing_module


@Injectable
class Db:
    pass


@Injectable
class UserService:
    def __init__(self, db: Db) -> None:
        self.db = db


class FakeUserService:
    def __init__(self, db: Db) -> None:
        self.db = db


@Module(providers=[Db, UserService], exports=[UserService])
class UsersModule:
    pass


@Module(imports=[UsersModule])
class AppModule:
    pass


checks: dict[str, bool] = {}


async def main() -> None:
    print("--- use_class replacement ---")
    try:
        compiled = await create_testing_module(AppModule).override_provider(UserService).use_class(FakeUserService).compile()
        print("OK:", compiled.get(UserService))
        checks["use_class_fails"] = False
    except ProviderResolutionError as exc:
        print("ProviderResolutionError:", exc)
        checks["use_class_fails"] = "not available to AppModule" in str(exc)

    print("--- use_factory replacement with inject=(Db,) ---")
    try:
        compiled = await (
            create_testing_module(AppModule)
            .override_provider(UserService)
            .use_factory(lambda db: FakeUserService(db), inject=(Db,))
            .compile()
        )
        print("OK:", compiled.get(UserService))
        checks["use_factory_fails"] = False
    except ProviderResolutionError as exc:
        print("ProviderResolutionError:", exc)
        checks["use_factory_fails"] = "not available to AppModule" in str(exc)

    print("--- control: same replacement resolved from the declaring module works ---")
    from bustan.app.bootstrap import create_app_context

    ctx = create_app_context(AppModule)
    inst = ctx.container.instantiate_class(FakeUserService, module=UsersModule)
    print("instantiate_class(FakeUserService, module=UsersModule) ->", type(inst).__name__, "db:", type(inst.db).__name__)
    checks["control_declaring_module_works"] = isinstance(inst, FakeUserService)
    # and the override manager does know the declaring module:
    from bustan.core.ioc.overrides import OverrideManager

    om = ctx.container.override_manager
    print("OverrideManager resolves declaring module ->", om._resolve_override_key(UserService, None)[0].__name__)
    checks["override_manager_knows_declaring_module"] = om._resolve_override_key(UserService, None)[0] is UsersModule

    print("--- sanity: the same overrides work when Db IS exported (so it is a visibility issue) ---")

    @Module(providers=[Db, UserService], exports=[UserService, Db])
    class UsersModuleExporting:
        pass

    @Module(imports=[UsersModuleExporting])
    class AppModule2:
        pass

    compiled = await create_testing_module(AppModule2).override_provider(UserService).use_class(FakeUserService).compile()
    print("with Db exported ->", type(compiled.get(UserService)).__name__)
    checks["works_when_exported"] = isinstance(compiled.get(UserService), FakeUserService)


anyio.run(main)
print("checks:", checks)
if all(checks.values()):
    print("CONFIRMED: builder replacements are resolved from the root module and cannot see the replaced provider's non-exported dependencies")
else:
    print("REFUTED (some checks false):", {k: v for k, v in checks.items() if not v})
