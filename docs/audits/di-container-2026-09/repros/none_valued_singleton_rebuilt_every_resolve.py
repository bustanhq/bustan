"""LEAD-07: every cache lookup treats None as 'not cached', so a singleton factory that legitimately
returns None (or a use_value of None) is re-executed on every resolution.
"""

from bustan import InjectionToken, Module, create_app_context

FEATURE_FLAG_CLIENT = InjectionToken("FEATURE_FLAG_CLIENT")
calls = {"count": 0}


def build_client() -> None:
    calls["count"] += 1
    return None  # e.g. feature flags disabled in this environment


@Module(providers=[{"provide": FEATURE_FLAG_CLIENT, "use_factory": build_client}])
class AppModule:
    pass


def main() -> None:
    context = create_app_context(AppModule)
    for _ in range(5):
        context.get(FEATURE_FLAG_CLIENT)
    if calls["count"] > 1:
        print(f"RESULT: LEAD-07 REPRODUCED - singleton factory ran {calls['count']} times for 5 resolves")
    else:
        print("RESULT: LEAD-07 FIXED - singleton factory ran once")


if __name__ == "__main__":
    main()
