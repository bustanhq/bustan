"""RF-02 and RF-04: constructor defaults are ignored and X | None is treated as an opaque token, so
ordinary Python constructors fail to resolve unless every parameter is a registered provider or
carries OptionalDep().
"""

from bustan import Injectable, Module, create_app_context
from bustan.errors import ProviderResolutionError


class Missing:
    pass


@Injectable()
class UsesUnion:
    def __init__(self, dep: Missing | None = None) -> None:
        self.dep = dep


@Injectable()
class UsesDefault:
    def __init__(self, retries: int = 3) -> None:
        self.retries = retries


def main() -> None:
    for cls, label in ((UsesUnion, "RF-02"), (UsesDefault, "RF-04")):
        module = Module(providers=[cls])(type("TestModule", (), {}))
        try:
            create_app_context(module).get(cls)
            print(f"RESULT: {label} FIXED - {cls.__name__} resolved using its default")
        except ProviderResolutionError as exc:
            print(f"RESULT: {label} REPRODUCED - {cls.__name__}: {str(exc)[-70:]}")


if __name__ == "__main__":
    main()
