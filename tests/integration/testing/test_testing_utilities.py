"""Integration tests for test-time provider override helpers."""

from typing import Annotated, Any, cast

import pytest
from starlette.testclient import TestClient

from bustan import Controller, Get, Inject, Injectable, Module, create_app
from bustan.testing import create_test_app, create_testing_module, override_provider


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

    @Module(
        controllers=[GreetingController], providers=[GreetingService], exports=[GreetingService]
    )
    class AppModule:
        pass

    application = create_test_app(
        AppModule,
        provider_overrides={GreetingService: FakeGreetingService()},
    )

    with TestClient(cast(Any, application)) as client:
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

    @Module(
        controllers=[GreetingController], providers=[GreetingService], exports=[GreetingService]
    )
    class AppModule:
        pass

    first_application = create_app(AppModule)
    second_application = create_app(AppModule)

    with (
        TestClient(cast(Any, first_application)) as first_client,
        TestClient(cast(Any, second_application)) as second_client,
    ):
        assert first_client.get("/greetings").json() == {"message": "production"}
        assert second_client.get("/greetings").json() == {"message": "production"}

        with override_provider(first_application, GreetingService, FakeGreetingService()):
            assert first_client.get("/greetings").json() == {"message": "test"}
            assert second_client.get("/greetings").json() == {"message": "production"}

        assert first_client.get("/greetings").json() == {"message": "production"}
        assert second_client.get("/greetings").json() == {"message": "production"}


@pytest.mark.anyio
async def test_compiled_testing_module_serves_a_graph_built_by_an_async_factory() -> None:
    # A compiled testing module runs the application's own startup, so an async
    # singleton factory is warmed before the first request rather than refused.
    async def build_connection() -> str:
        return "conn-1"

    @Controller("/connections")
    class ConnectionController:
        def __init__(self, connection: Annotated[str, Inject("CONN")]) -> None:
            self.connection = connection

        @Get("/")
        def read_connection(self) -> dict[str, str]:
            return {"connection": self.connection}

    @Module(
        providers=[{"provide": "CONN", "use_factory": build_connection}],
        exports=["CONN"],
    )
    class DbModule:
        pass

    @Module(imports=[DbModule], controllers=[ConnectionController])
    class AppModule:
        pass

    compiled = await create_testing_module(AppModule).compile()
    try:
        with compiled.create_client() as client:
            response = client.get("/connections")

        assert response.status_code == 200
        assert response.json() == {"connection": "conn-1"}
    finally:
        await compiled.close()


@pytest.mark.anyio
async def test_compiled_testing_module_serves_a_replacement_built_in_its_own_module() -> None:
    # The fake shares the real provider's constructor, and its dependency is private
    # to the module that declares the provider it replaces.
    @Injectable
    class Db:
        def rows(self) -> list[str]:
            return ["production"]

    @Injectable
    class UserService:
        def __init__(self, db: Db) -> None:
            self.db = db

        def names(self) -> list[str]:
            return self.db.rows()

    class FakeUserService:
        def __init__(self, db: Db) -> None:
            self.db = db

        def names(self) -> list[str]:
            return [*self.db.rows(), "fake"]

    @Controller("/users")
    class UsersController:
        def __init__(self, user_service: UserService) -> None:
            self.user_service = user_service

        @Get("/")
        def read_users(self) -> dict[str, list[str]]:
            return {"names": self.user_service.names()}

    @Module(providers=[Db, UserService], exports=[UserService])
    class UsersModule:
        pass

    @Module(imports=[UsersModule], controllers=[UsersController])
    class AppModule:
        pass

    compiled = await (
        create_testing_module(AppModule)
        .override_provider(UserService)
        .use_class(FakeUserService)
        .compile()
    )
    try:
        with compiled.create_client() as client:
            response = client.get("/users")

        assert response.status_code == 200
        assert response.json() == {"names": ["production", "fake"]}
    finally:
        await compiled.close()
