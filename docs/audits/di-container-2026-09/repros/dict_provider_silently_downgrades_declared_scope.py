"""RI-02: binding an @Injectable(scope="request") class under an interface token with a dict
provider that omits the scope key silently produces a SINGLETON binding. Per-request state on that
class is then shared by every request.
"""

from bustan import Injectable, InjectionToken, Module, Scope
from bustan.kernel.ioc.registry import normalize_provider


@Injectable(scope=Scope.REQUEST)
class PerRequestAudit:
    def __init__(self) -> None:
        self.events: list[str] = []


AUDIT = InjectionToken("AUDIT")


@Module(providers=[{"provide": AUDIT, "use_class": PerRequestAudit}])
class AppModule:
    pass


def main() -> None:
    binding = normalize_provider({"provide": AUDIT, "use_class": PerRequestAudit}, AppModule)
    if binding.scope is Scope.SINGLETON:
        print(
            "RESULT: RI-02 REPRODUCED - class declares scope=request but the binding is singleton"
        )
    else:
        print(f"RESULT: RI-02 FIXED - binding scope is {binding.scope.value}")


if __name__ == "__main__":
    main()
