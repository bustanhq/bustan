"""OL-01: Container.override only clears cached controller singletons. A provider singleton that
already captured the original dependency keeps it, so override_provider silently has no effect on
anything constructed before the override.
"""

from bustan import Injectable, Module, create_app_context
from bustan.testing import override_provider


@Injectable()
class Clock:
    def now(self) -> str:
        return "real"


@Injectable()
class ReportService:
    def __init__(self, clock: Clock) -> None:
        self.clock = clock

    def stamp(self) -> str:
        return self.clock.now()


class FakeClock:
    def now(self) -> str:
        return "fake"


@Module(providers=[Clock, ReportService])
class AppModule:
    pass


def main() -> None:
    context = create_app_context(AppModule)
    context.get(ReportService)  # constructed before the override, as after startup
    with override_provider(context.container, Clock, FakeClock()):
        seen = context.get(ReportService).stamp()
    if seen == "real":
        print(
            "RESULT: OL-01 REPRODUCED - ReportService still used the real Clock during the override"
        )
    else:
        print("RESULT: OL-01 FIXED - dependent observed the override")


if __name__ == "__main__":
    main()
