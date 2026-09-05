import asyncio

from starlette.testclient import TestClient
from testing_overrides import compile_with_fake_greeting
from testing_overrides.app_module import AppModule
from testing_overrides.fake_greeting_service import FakeGreetingService
from testing_overrides.greeting_service import GreetingService

from bustan.testing import create_test_app


def test_create_test_app_applies_provider_overrides() -> None:
    application = create_test_app(
        AppModule,
        provider_overrides={GreetingService: FakeGreetingService("from test")},
    )

    with TestClient(application) as client:
        response = client.get("/greetings")

    assert response.status_code == 200
    assert response.json() == {"message": "from test"}


def test_a_compiled_testing_module_serves_the_replacement() -> None:
    compiled = compile_with_fake_greeting("from testing module")

    try:
        with compiled.create_client() as client:
            response = client.get("/greetings")
    finally:
        asyncio.run(compiled.close())

    assert response.status_code == 200
    assert response.json() == {"message": "from testing module"}


def test_an_application_built_without_an_override_serves_the_real_provider() -> None:
    application = create_test_app(AppModule)

    with TestClient(application) as client:
        response = client.get("/greetings")

    assert response.json() == {"message": "production"}
