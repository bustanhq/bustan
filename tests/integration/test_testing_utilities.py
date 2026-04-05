"""Integration tests for test-time provider override helpers."""

from starlette.testclient import TestClient

from bustan import Controller, create_app, Get, Injectable, Module
from bustan.testing import create_test_app, override_provider


def test_create_test_app_applies_provider_overrides() -> None:
    @Injectable
    class GreetingService:
        def greet(self) -> str:
            return "production"

    class FakeGreetingService:
        def greet(self) -> str:
            return "test"

    @Controller("/greetings")
    class GreetingController:
        def __init__(self, greeting_service: GreetingService) -> None:
            self.greeting_service = greeting_service

        @Get("/")
        def read_greeting(self) -> dict[str, str]:
            return {"message": self.greeting_service.greet()}

    @Module(controllers=[GreetingController], providers=[GreetingService], exports=[GreetingService])
    class AppModule:
        pass

    application = create_test_app(
        AppModule,
        provider_overrides={GreetingService: FakeGreetingService()},
    )

    with TestClient(application) as client:
        response = client.get("/greetings")

    assert response.status_code == 200
    assert response.json() == {"message": "test"}


def test_override_provider_is_scoped_and_does_not_leak_between_apps() -> None:
    @Injectable
    class GreetingService:
        def greet(self) -> str:
            return "production"

    class FakeGreetingService:
        def greet(self) -> str:
            return "test"

    @Controller("/greetings")
    class GreetingController:
        def __init__(self, greeting_service: GreetingService) -> None:
            self.greeting_service = greeting_service

        @Get("/")
        def read_greeting(self) -> dict[str, str]:
            return {"message": self.greeting_service.greet()}

    @Module(controllers=[GreetingController], providers=[GreetingService], exports=[GreetingService])
    class AppModule:
        pass

    first_application = create_app(AppModule)
    second_application = create_app(AppModule)

    with TestClient(first_application) as first_client, TestClient(second_application) as second_client:
        assert first_client.get("/greetings").json() == {"message": "production"}
        assert second_client.get("/greetings").json() == {"message": "production"}

        with override_provider(first_application, GreetingService, FakeGreetingService()):
            assert first_client.get("/greetings").json() == {"message": "test"}
            assert second_client.get("/greetings").json() == {"message": "production"}

        assert first_client.get("/greetings").json() == {"message": "production"}
        assert second_client.get("/greetings").json() == {"message": "production"}