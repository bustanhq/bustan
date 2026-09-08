"""DP-01: ModuleRef injected through DI is root-module scoped rather than scoped to the module
that received it, and strict=False resolves against the root instead of searching the container,
so a child module's service can reach its own non-exported providers by neither route.
"""

from bustan import DiscoveryModule, Injectable, Module, ModuleRef, create_app_context
from bustan.errors import BustanError


@Injectable()
class PrivateInChild:
    pass


@Injectable()
class ChildService:
    def __init__(self, module_ref: ModuleRef) -> None:
        self.module_ref = module_ref


@Module(
    imports=[DiscoveryModule],
    providers=[PrivateInChild, ChildService],
    exports=[ChildService],
)
class ChildModule:
    pass


@Module(imports=[ChildModule, DiscoveryModule])
class AppModule:
    pass


@Injectable()
class SiblingPrivate:
    pass


@Module(providers=[SiblingPrivate])
class SiblingModule:
    pass


@Module(providers=[SiblingPrivate])
class RivalModule:
    pass


@Module(imports=[SiblingModule, DiscoveryModule])
class OneCandidateApp:
    pass


@Module(imports=[SiblingModule, RivalModule, DiscoveryModule])
class TwoCandidateApp:
    pass


def _outcome(call: object) -> str:
    """Run a lookup and report what it answered with, without letting it end the script."""

    try:
        return type(call()).__name__  # type: ignore[operator]
    except BustanError as exc:
        return f"{type(exc).__name__}: {exc}"


def main() -> None:
    child_ref = create_app_context(AppModule).get(ChildService).module_ref
    host = getattr(child_ref.module_key, "__name__", child_ref.module_key)
    strict = _outcome(lambda: child_ref.get(PrivateInChild))
    non_strict = _outcome(lambda: child_ref.get(PrivateInChild, strict=False))

    root_ref = create_app_context(OneCandidateApp).get(ModuleRef)
    sibling = _outcome(lambda: root_ref.get(SiblingPrivate, strict=False))

    rival_ref = create_app_context(TwoCandidateApp).get(ModuleRef)
    ambiguous = _outcome(lambda: rival_ref.get(SiblingPrivate, strict=False))

    scoped = host == "ChildModule"
    reaches_own = strict == "PrivateInChild" and non_strict == "PrivateInChild"
    searches = sibling == "SiblingPrivate"
    refuses_ambiguity = ambiguous.startswith("ProviderResolutionError")

    if scoped and reaches_own and searches and refuses_ambiguity:
        print(
            "RESULT: DP-01 FIXED - the reference is scoped to ChildModule, resolves its private "
            "provider strict and non-strict, finds a sibling module's private provider, and "
            "refuses two candidates"
        )
        return
    print(
        f"RESULT: DP-01 REPRODUCED - host module {host}, strict {strict}, non-strict "
        f"{non_strict}, sibling lookup {sibling}, two candidates {ambiguous}"
    )


if __name__ == "__main__":
    main()
