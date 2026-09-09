"""DP-03: two of the smaller parity gaps, settled differently from each other.

A NestJS-style mapping written as a factory inject entry escaped the visibility lookup as
a raw TypeError instead of a framework error; that is a defect and is fixed. INQUIRER
yielding the requesting class rather than the requesting instance is not a defect: Bustan
injects through the constructor only, so at the moment INQUIRER is answered the consumer's
__init__ has not run and no instance of it exists. That gap is documented as a deliberate
difference in docs/COMPARISONS.md, and this script holds the framework to it.
"""

from typing import Annotated

from bustan import INQUIRER, FactoryProvider, Inject, Injectable, Module, Scope, create_app_context
from bustan.errors import BustanError


@Injectable(scope=Scope.TRANSIENT)
class Journal:
    def __init__(self, inquirer: Annotated[object, Inject(INQUIRER)]) -> None:
        self.inquirer = inquirer


@Injectable()
class Orders:
    def __init__(self, journal: Journal) -> None:
        self.journal = journal


@Module(providers=[Journal, Orders], exports=[Orders])
class InquirerModule:
    pass


@Module(
    providers=[
        FactoryProvider(
            provide="settings",
            use_factory=lambda value: value,
            inject=({"token": "missing", "optional": True},),
        )
    ]
)
class MappingInjectModule:
    pass


def _inquirer_answer() -> str:
    """Report what INQUIRER hands the transient provider one level down."""

    try:
        answered = create_app_context(InquirerModule).get(Orders).journal.inquirer
    except BustanError as exc:
        return f"{type(exc).__name__}: {exc}"
    if answered is Orders:
        return "the requesting class, as documented"
    if isinstance(answered, Orders):
        return "an instance of the requesting class"
    return f"neither the class nor an instance: {answered!r}"


def _mapping_inject_answer() -> str:
    """Report how a mapping written where a factory's token belongs is refused."""

    try:
        create_app_context(MappingInjectModule).get("settings")
    except BustanError as exc:
        message = str(exc)
        names_all = all(
            part in message for part in ("MappingInjectModule", "'settings'", "'token'")
        )
        detail = "naming the module, the token and the entry" if names_all else "without naming it"
        return f"a framework {type(exc).__name__} {detail}"
    except TypeError as exc:
        return f"a raw TypeError: {exc}"
    return "no error at all"


def main() -> None:
    inquirer = _inquirer_answer()
    mapping_inject = _mapping_inject_answer()

    documented = inquirer == "the requesting class, as documented"
    refused = mapping_inject.startswith("a framework") and mapping_inject.endswith(
        "naming the module, the token and the entry"
    )

    if documented and refused:
        print(
            f"RESULT: DP-03 FIXED - the mapping inject entry raises {mapping_inject}, and "
            f"INQUIRER yields {inquirer}"
        )
        return
    print(
        f"RESULT: DP-03 REPRODUCED - the mapping inject entry raises {mapping_inject}; INQUIRER "
        f"yields {inquirer}"
    )


if __name__ == "__main__":
    main()
