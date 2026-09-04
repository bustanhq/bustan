"""MG-02: two global modules exporting the same token are accepted silently; which one wins
depends on module discovery order (first global wins), so re-ordering imports changes behavior.
"""

from bustan import Global, InjectionToken, Module, create_app_context

TOKEN = InjectionToken("SHARED")


@Global()
@Module(providers=[{"provide": TOKEN, "use_value": "from-G1"}], exports=[TOKEN])
class G1:
    pass


@Global()
@Module(providers=[{"provide": TOKEN, "use_value": "from-G2"}], exports=[TOKEN])
class G2:
    pass


@Module(imports=[G1, G2])
class AppA:
    pass


@Module(imports=[G2, G1])
class AppB:
    pass


def main() -> None:
    try:
        first = create_app_context(AppA).get(TOKEN)
        second = create_app_context(AppB).get(TOKEN)
    except Exception as exc:  # noqa: BLE001 - a rejection of the ambiguity is the fixed state
        print(f"RESULT: MG-02 FIXED - ambiguity rejected: {type(exc).__name__}")
        return
    if first != second:
        print(f"RESULT: MG-02 REPRODUCED - imports=[G1,G2] -> {first}, imports=[G2,G1] -> {second}, no error")
    else:
        print("RESULT: MG-02 FIXED - deterministic winner or rejection")


if __name__ == "__main__":
    main()
