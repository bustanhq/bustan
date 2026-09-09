"""MG-08: a dynamic registration's metadata is concatenated onto its base module's, so a provider
for a token the base already declares is rejected as a duplicate instead of replacing the default,
and an import the base already names is rejected as a duplicate too.
"""

from bustan import DynamicModule, InjectionToken, Module, ValueProvider, create_app_context
from bustan.errors import BustanError

OPTIONS = InjectionToken("OPTIONS")


@Module(providers=[ValueProvider(provide=OPTIONS, use_value="default")], exports=[OPTIONS])
class BaseModule:
    pass


@Module(providers=[ValueProvider(provide="shared", use_value="shared")], exports=["shared"])
class SharedModule:
    pass


@Module(imports=[SharedModule], exports=["shared"])
class ImportingBase:
    pass


def _outcome(build: object) -> str:
    """Build an application from a registration and report what it answered with."""

    try:
        return repr(build())  # type: ignore[operator]
    except BustanError as exc:
        return f"{type(exc).__name__}: {exc}"


def main() -> None:
    overridden = _outcome(
        lambda: create_app_context(
            DynamicModule(
                BaseModule, providers=(ValueProvider(provide=OPTIONS, use_value="configured"),)
            )
        ).get(OPTIONS)
    )
    reimported = _outcome(
        lambda: create_app_context(DynamicModule(ImportingBase, imports=(SharedModule,))).get(
            "shared"
        )
    )

    if overridden == "'configured'" and reimported == "'shared'":
        print(
            "RESULT: MG-08 FIXED - the registration's provider replaced the base default and "
            "re-naming a base import was accepted"
        )
        return
    print(
        f"RESULT: MG-08 REPRODUCED - override answered {overridden}, re-named import answered "
        f"{reimported}"
    )


if __name__ == "__main__":
    main()
