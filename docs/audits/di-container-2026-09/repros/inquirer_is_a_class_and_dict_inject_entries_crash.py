"""DP-03: two of the smaller parity gaps. INQUIRER hands the transient provider the requesting
class rather than the instance being built, and a NestJS-style mapping written as a factory
inject entry escapes the visibility lookup as a raw TypeError instead of a framework error.
"""

from typing import Annotated

from bustan import INQUIRER, Inject, Injectable, Module, create_app_context
from bustan.errors import BustanError


@Injectable(scope="transient")
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
        {
            "provide": "settings",
            "use_factory": lambda value: value,
            "inject": ({"token": "missing", "optional": True},),
        }
    ]
)
class MappingInjectModule:
    pass


def _inquirer_answer() -> str:
    """Report what INQUIRER handed the transient provider one level down."""

    try:
        answered = create_app_context(InquirerModule).get(Orders).journal.inquirer
    except BustanError as exc:
        return f"{type(exc).__name__}: {exc}"
    return "the instance" if isinstance(answered, Orders) else f"the class {answered!r}"


def _mapping_inject_answer() -> str:
    """Report how a mapping written where a factory's token belongs is refused."""

    try:
        create_app_context(MappingInjectModule).get("settings")
    except BustanError as exc:
        return f"framework error {type(exc).__name__}: {exc}"
    except TypeError as exc:
        return f"raw TypeError: {exc}"
    return "accepted silently"


def main() -> None:
    inquirer = _inquirer_answer()
    mapping_inject = _mapping_inject_answer()

    if inquirer == "the instance" and mapping_inject.startswith("framework error"):
        print(f"RESULT: DP-03 FIXED - INQUIRER yields {inquirer}, and {mapping_inject}")
        return
    print(
        f"RESULT: DP-03 REPRODUCED - INQUIRER yields {inquirer}; the mapping inject entry gives "
        f"{mapping_inject}"
    )


if __name__ == "__main__":
    main()
