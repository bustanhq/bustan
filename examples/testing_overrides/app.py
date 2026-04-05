"""Example showing test-time provider overrides with bustan.testing."""

from bustan import Controller, create_app, Get, Injectable, Module
from bustan.testing import create_test_app, override_provider
from starlette.testclient import TestClient


@Injectable
class GreetingService:
    def greet(self) -> str:
        return "production"


class FakeGreetingService:
    def __init__(self, message: str) -> None:
        self.message = message

    def greet(self) -> str:
        return self.message


@Controller("/greetings")
class GreetingController:
    def __init__(self, greeting_service: GreetingService) -> None:
        self.greeting_service = greeting_service

    @Get("/")
    def read_greeting(self) -> dict[str, str]:
        return {"message": self.greeting_service.greet()}


@Module(
    controllers=[GreetingController],
    providers=[GreetingService],
    exports=[GreetingService],
)
class AppModule:
    pass


app = create_app(AppModule)


def demo_overrides() -> None:
    """Print responses before, during, and after provider overrides."""

    application = create_test_app(
        AppModule,
        provider_overrides={GreetingService: FakeGreetingService("from create_test_app")},
    )

    with TestClient(application) as client:
        print(client.get("/greetings").json())

    application = create_test_app(AppModule)
    with TestClient(application) as client:
        print(client.get("/greetings").json())
        with override_provider(application, GreetingService, FakeGreetingService("from override_provider")):
            print(client.get("/greetings").json())
        print(client.get("/greetings").json())


if __name__ == "__main__":
    demo_overrides()