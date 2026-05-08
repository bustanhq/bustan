from starlette.testclient import TestClient

from bustan.testing import create_test_app, override_provider

from testing_overrides.app_module import AppModule
from testing_overrides.fake_greeting_service import FakeGreetingService
from testing_overrides.greeting_service import GreetingService


def test_create_test_app_applies_provider_overrides() -> None:
    application = create_test_app(
        AppModule,
        provider_overrides={GreetingService: FakeGreetingService("from test")},
    )

    with TestClient(application) as client:
        response = client.get("/greetings")

    assert response.status_code == 200
    assert response.json() == {"message": "from test"}


def test_override_provider_is_scoped() -> None:
    application = create_test_app(AppModule)

    with TestClient(application) as client:
        before = client.get("/greetings")
        with override_provider(application, GreetingService, FakeGreetingService("temporary")):
            during = client.get("/greetings")
        after = client.get("/greetings")

    assert before.json() == {"message": "production"}
    assert during.json() == {"message": "temporary"}
    assert after.json() == {"message": "production"}