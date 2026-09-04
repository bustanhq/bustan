# ruff: noqa
"""A `use_class` dict binding ignores the class's own declared scope.

A class decorated `@Injectable(scope=Scope.REQUEST)` and bound under an interface
token with `{"provide": Iface, "use_class": Cls}` is registered as a process-wide
singleton, so every caller shares one instance of a provider the author declared
per-request.
"""

from __future__ import annotations

from bustan import Injectable, Module, Scope, create_app_context
from bustan.common.constants import BUSTAN_PROVIDER_ATTR
from bustan.core.ioc.registry import normalize_provider


class AuditPort:
    pass


@Injectable(scope=Scope.REQUEST)
class RequestAudit(AuditPort):
    pass


@Module(providers=[{"provide": AuditPort, "use_class": RequestAudit}])
class AppModule:
    pass


def main() -> None:
    binding = normalize_provider(
        {"provide": AuditPort, "use_class": RequestAudit}, AppModule
    )
    declared = getattr(RequestAudit, BUSTAN_PROVIDER_ATTR, {}).get("scope")
    print(f"class declares scope: {declared}")
    print(f"dict binding registers scope: {binding.scope}")

    context = create_app_context(AppModule)
    first = context.get(AuditPort)
    second = context.get(AuditPort)
    shared = first is second
    print(f"two resolutions returned the same instance: {shared}")

    if binding.scope is Scope.REQUEST:
        print("RESULT: RI-02 FIXED - the dict binding inherits the class's declared scope")
    else:
        print(
            "RESULT: RI-02 REPRODUCED - class declares "
            f"{declared} but the dict binding registers {binding.scope}"
        )


main()
