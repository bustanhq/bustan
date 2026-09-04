"""LEAD-16: provider tokens are used as dict keys without validation; an unhashable provide value
escapes as a raw TypeError instead of InvalidProviderError.
"""

from bustan import Module, create_app_context
from bustan.errors import BustanError


def main() -> None:
    try:
        module = Module(providers=[{"provide": {"name": "x"}, "use_value": 1}])(type("BadModule", (), {}))
        create_app_context(module)
        print("RESULT: LEAD-16 REPRODUCED - unhashable token accepted silently")
    except BustanError as exc:
        print(f"RESULT: LEAD-16 FIXED - framework error {type(exc).__name__}")
    except TypeError as exc:
        print(f"RESULT: LEAD-16 REPRODUCED - raw TypeError escaped: {exc}")


if __name__ == "__main__":
    main()
