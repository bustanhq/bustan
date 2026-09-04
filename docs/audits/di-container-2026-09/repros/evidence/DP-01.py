# ruff: noqa
# Evidence script for finding DP-01 (workflow id F-47) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-47: ModuleRef injected through DI is root-module scoped; strict=False is not a container-wide lookup.

ChildModule provides PrivateInChild (not exported) and ChildService(ref: ModuleRef).
Expected per finding: ref.module_key is AppModule; get(PrivateInChild) fails for strict=True and strict=False;
for_module(ChildModule).get(PrivateInChild) works.
"""
from __future__ import annotations

from bustan import DiscoveryModule, Injectable, Module, ModuleRef, create_app
from bustan.core.errors import ProviderResolutionError


@Injectable()
class PrivateInChild:
    pass


@Injectable()
class ChildService:
    def __init__(self, ref: ModuleRef) -> None:
        self.ref = ref


@Module(imports=[DiscoveryModule], providers=[PrivateInChild, ChildService], exports=[ChildService])
class ChildModule:
    pass


@Module(imports=[ChildModule, DiscoveryModule])
class AppModule:
    pass


app = create_app(AppModule)
svc = app.get(ChildService)
key = svc.ref.module_key
print("ModuleRef injected into ChildService (declared in ChildModule): module_key =", getattr(key, "__name__", key))

outcomes: dict[bool, str] = {}
for strict in (True, False):
    try:
        svc.ref.get(PrivateInChild, strict=strict)
        outcomes[strict] = "OK"
    except ProviderResolutionError as exc:
        outcomes[strict] = f"ProviderResolutionError: {str(exc)[:110]}"
    print(f"ref.get(PrivateInChild, strict={strict}) -> {outcomes[strict]}")

scoped = svc.ref.for_module(ChildModule)
print("ref.for_module(ChildModule).module_key =", scoped.module_key.__name__)
print("ref.for_module(ChildModule).get(PrivateInChild) ->", type(scoped.get(PrivateInChild)).__name__)

# also: does strict=False find a provider that lives only in a sibling module not visible to the root?
@Injectable()
class SiblingPrivate:
    pass


@Module(providers=[SiblingPrivate])
class SiblingModule:
    pass


@Module(imports=[SiblingModule, DiscoveryModule])
class App2:
    pass


app2 = create_app(App2)
root_ref = app2.get(ModuleRef)
try:
    root_ref.get(SiblingPrivate, strict=False)
    sibling = "OK (container-wide)"
except ProviderResolutionError as exc:
    sibling = f"ProviderResolutionError: {str(exc)[:90]}"
print("root ModuleRef.get(SiblingPrivate, strict=False) ->", sibling)

if key is AppModule and all(v.startswith("ProviderResolutionError") for v in outcomes.values()) and sibling.startswith("ProviderResolutionError"):
    print("PASS: DI-injected ModuleRef is root-scoped and strict=False does not search the whole container")
else:
    print("FAIL: behavior differs from the finding")
