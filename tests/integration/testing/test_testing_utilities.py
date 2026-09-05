"""Integration tests for test-time provider override helpers."""

from typing import Annotated, Any, cast

import pytest
from starlette.testclient import TestClient

from bustan import (
    Controller,
    Get,
    Inject,
    Injectable,
    Module,
    create_app,
    create_app_context,
)
from bustan.errors import ProviderResolutionError
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


@pytest.mark.anyio
async def test_an_override_does_not_leak_between_applications() -> None:
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

    overridden = await (
        create_testing_module(AppModule)
        .override_provider(GreetingService)
        .use_value(FakeGreetingService())
        .compile()
    )
    untouched = await create_testing_module(AppModule).compile()

    try:
        with (
            overridden.create_client() as overridden_client,
            untouched.create_client() as untouched_client,
        ):
            assert overridden_client.get("/greetings").json() == {"message": "test"}
            assert untouched_client.get("/greetings").json() == {"message": "production"}
    finally:
        await untouched.close()
        await overridden.close()


@pytest.mark.anyio
async def test_an_override_is_refused_once_the_application_has_started() -> None:
    @Injectable
    class GreetingService:
        def greet(self) -> str:
            return "production"

    @Module(providers=[GreetingService], exports=[GreetingService])
    class AppModule:
        pass

    context = await create_app_context(AppModule).init()

    with pytest.raises(ProviderResolutionError) as raised:
        context.container.override(GreetingService, object())

    assert "GreetingService" in str(raised.value)
    assert "before startup" in str(raised.value)

    await context.close()


def test_an_override_is_refused_while_a_test_client_is_serving() -> None:
    @Injectable
    class GreetingService:
        def greet(self) -> str:
            return "production"

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

    class FakeGreetingService:
        def greet(self) -> str:
            return "test"

    application = create_app(AppModule)

    with TestClient(cast(Any, application)) as client:
        assert client.get("/greetings").json() == {"message": "production"}

        with pytest.raises(ProviderResolutionError) as direct:
            application.container.override(GreetingService, FakeGreetingService())

        with (
            pytest.raises(ProviderResolutionError) as helper,
            override_provider(application, GreetingService, FakeGreetingService()),
        ):
            pass  # pragma: no cover - the block body is never reached

        # The application kept serving the provider it started with, which is the
        # whole reason the replacement was refused rather than half applied.
        assert client.get("/greetings").json() == {"message": "production"}

    assert "GreetingService" in str(direct.value)
    assert "before startup" in str(direct.value)
    assert "create_testing_module" in str(helper.value)
    assert "before startup" in str(helper.value)


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
