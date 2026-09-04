"""LEAD-17: provider lifecycle stages call any attribute named like a hook on EVERY cached singleton,
including use_value objects the framework never constructed. A MagicMock (or any SDK object with a
matching attribute name) gets all five hooks invoked.
"""

from unittest.mock import MagicMock

import anyio

from bustan import InjectionToken, Module, create_app_context

CLIENT = InjectionToken("CLIENT")
client = MagicMock()


@Module(providers=[{"provide": CLIENT, "use_value": client}])
class AppModule:
    pass


async def run() -> None:
    context = create_app_context(AppModule)
    await context.init()
    await context.close()


def main() -> None:
    anyio.run(run)
    invoked = [call[0] for call in client.method_calls]
    if invoked:
        print(f"RESULT: LEAD-17 REPRODUCED - hooks invoked on a use_value object: {invoked}")
    else:
        print("RESULT: LEAD-17 FIXED - value providers are not treated as lifecycle participants")


if __name__ == "__main__":
    main()
